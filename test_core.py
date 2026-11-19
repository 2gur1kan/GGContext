"""Çekirdek mantık testleri:  python test_core.py"""
import contextlib
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="bk_test_")
os.environ["BK_DATA_DIR"] = _TMP  # gerçek veriye dokunma

import baglam_core as core  # noqa: E402


def lorem(nChars: int, seed: str = "kelime") -> str:
    out, i = [], 0
    while sum(len(gg) + 1 for gg in out) < nChars:
        out.append(f"{seed}{i}")
        i += 1
    return " ".join(out)[:nChars]


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.store = core.Store(Path(_TMP) / f"t_{self._testMethodName}.db")
        self.work = Path(tempfile.mkdtemp(prefix="bk_work_"))
        self.tid = self.store.CreateTopic("Deneme Konusu")

    def tearDown(self): self.store.close()

    def MakeFiles(self, n=5, size=5000):
        proj = self.work / "proje"
        proj.mkdir()
        for i in range(n):
            (proj / f"modul{i}.py").write_text(f"# modul {i}\n" + lorem(size, f"m{i}_"), encoding="utf-8")
        self.store.AddSource(self.tid, proj)
        return proj

    #################### temel yardımcılar

    def testTruncate(self):
        short = "merhaba dünya"
        self.assertEqual(core.TruncateToTokens(short, 100), short)
        long = lorem(20000)
        for limit in (10, 50, 300, 1000):
            out = core.TruncateToTokens(long, limit)
            self.assertLessEqual(core.EstimateTokens(out), limit)
        self.assertEqual(core.TruncateToTokens(long, 0), "")

    def testMaskSecrets(self):
        t = (
            "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456\n"
            "password = hunter22\n"
            "Authorization: Bearer abcdef1234567890xyz\n"
            "max_tokens = 100000\n"
            "token = os.environ['X']\n"
        )
        out = core.MaskSecrets(t)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", out)
        self.assertNotIn("hunter22", out)
        self.assertNotIn("abcdef1234567890xyz", out)
        self.assertIn("max_tokens = 100000", out)       # sayı: dokunulmaz
        self.assertIn("os.environ['X']", out)           # kod ifadesi: dokunulmaz

    #################### veritabanı

    def testCrudAndDedupe(self):
        e1 = self.store.AddEntry(self.tid, "Claude", "ilk cevap", skipDuplicateFlag=True)
        self.assertIsNotNone(e1)
        self.assertIsNone(self.store.AddEntry(self.tid, "Claude", "ilk cevap", skipDuplicateFlag=True))
        self.assertIsNone(self.store.AddEntry(self.tid, "Claude", "   "))
        self.store.AddEntry(self.tid, "Gemini", "ikinci")
        self.assertEqual(len(self.store.ListEntries(self.tid)), 2)
        i1 = self.store.AddItem(self.tid, "decision", "SQLite kullanılacak")
        self.store.AddItem(self.tid, "open", "Test yaz")
        self.store.SetItemDone(self.store.ListItems(self.tid)[1]["id"], True)
        self.assertEqual(len(self.store.ListItems(self.tid)), 2)
        self.store.DeleteItem(i1)
        self.assertEqual(len(self.store.ListItems(self.tid)), 1)
        self.store.DeleteTopic(self.tid)  # cascade
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)

    #################### paket

    def testPackRespectsBudget(self):
        self.store.UpdateTopic(self.tid, goal="Hedef cümlesi", summary=lorem(3000, "ozet"))
        self.store.AddItem(self.tid, "decision", "Karar bir")
        self.store.AddItem(self.tid, "open", "Açık iş bir")
        for i in range(10):
            self.store.AddEntry(self.tid, "Claude" if i % 2 else "ChatGPT", f"MESAJ{i} " + lorem(2000, f"e{i}_"))
        self.MakeFiles(5, 5000)
        for budget in (1000, 2000, 4000, 8000, 16000):
            res = core.BuildPack(self.store, self.tid, core.PackOptions(budgetTokens=budget, lastN=4))
            self.assertLessEqual(res.tokens, budget, f"bütçe aşıldı: {res.tokens} > {budget}")
            self.assertFalse(res.overBudgetFlag)
            self.assertIn("MESAJ9", res.text)           # en son mesaj her zaman var
            self.assertIn("Karar bir", res.text)
            self.assertIn("Açık iş bir", res.text)
        # bol bütçede dosyalar da tam gelir
        big = core.BuildPack(self.store, self.tid, core.PackOptions(budgetTokens=60000, lastN=4))
        self.assertEqual(len(big.filesIncluded), 5)
        self.assertEqual(big.filesTrimmed, [])
        self.assertEqual(big.entriesIncluded, 4)

    def testRequestAndHeader(self):
        res = core.BuildPack(self.store, self.tid, core.PackOptions(), request="Bunu devam ettir")
        self.assertIn("## İstek\nBunu devam ettir", res.text)
        self.assertTrue(res.text.startswith(core.PACK_MARKER))
        res2 = core.BuildPack(self.store, self.tid, core.PackOptions())
        self.assertIn("Hazırım", res2.text)

    def testPinnedEntryIncludedBeyondLastN(self):
        old = self.store.AddEntry(self.tid, "Claude", "ESKI_ONEMLI " + lorem(200))
        self.store.SetPinned(old, True)
        for i in range(6): self.store.AddEntry(self.tid, "Gemini", f"yeni{i} " + lorem(200))
        res = core.BuildPack(self.store, self.tid, core.PackOptions(lastN=2, budgetTokens=8000))
        self.assertIn("ESKI_ONEMLI", res.text)
        self.assertNotIn("yeni1 ", res.text)

    def testDeltaMode(self):
        proj = self.MakeFiles(3, 1500)
        self.store.AddEntry(self.tid, "Claude", "ESKI_CEVAP " + lorem(300))
        opts = core.PackOptions(targetModel="Claude", budgetTokens=20000, deltaFlag=True)
        first = core.BuildPack(self.store, self.tid, opts)
        self.assertTrue(first.deltaFallbackFlag)            # önceki aktarım yok -> tam
        self.assertEqual(first.mode, "tam")
        self.store.RecordHandoff(self.tid, "Claude", first.lastEntryId, first.fileHashes)

        # hiçbir şey değişmediyse: dosya içeriği yok, yalnızca "değişmedi" notu
        same = core.BuildPack(self.store, self.tid, opts)
        self.assertEqual(same.mode, "fark")
        self.assertEqual(same.filesIncluded, [])
        self.assertEqual(len(same.filesUnchanged), 3)
        self.assertNotIn("ESKI_CEVAP", same.text)

        # bir dosya değişir + yeni cevap gelir
        (proj / "modul1.py").write_text("# DEGISTI\n" + lorem(500, "yeni_"), encoding="utf-8")
        self.store.AddEntry(self.tid, "Gemini", "YENI_CEVAP " + lorem(300))
        d = core.BuildPack(self.store, self.tid, opts)
        self.assertEqual(d.mode, "fark")
        self.assertIn("YENI_CEVAP", d.text)
        self.assertNotIn("ESKI_CEVAP", d.text)
        self.assertEqual(d.filesIncluded, ["proje/modul1.py"])
        self.assertEqual(len(d.filesUnchanged), 2)
        self.assertLess(d.tokens, first.tokens)          # fark paketi daha küçük

        # başka bir model için hâlâ tam paket
        other = core.BuildPack(self.store, self.tid, core.PackOptions(targetModel="Gemini", deltaFlag=True, budgetTokens=20000))
        self.assertEqual(other.mode, "tam")

    def testSensitiveAndEncoding(self):
        proj = self.work / "karma"
        proj.mkdir()
        (proj / ".env").write_text("GIZLI=cok-gizli-deger-12345", encoding="utf-8")
        (proj / "anahtar.pem").write_text("-----BEGIN-----", encoding="utf-8")
        (proj / "eski.txt").write_bytes("şğüöçı İ Türkçe karakter".encode("cp1254"))
        (proj / "yeni.txt").write_text("şğüöçı UTF-8", encoding="utf-8")
        (proj / "ikili.bin").write_bytes(b"\x00\x01\x02binary")
        self.store.AddSource(self.tid, proj)
        res = core.BuildPack(self.store, self.tid, core.PackOptions(budgetTokens=8000))
        self.assertNotIn("cok-gizli-deger", res.text)
        self.assertNotIn("BEGIN", res.text)
        self.assertEqual(res.sensitiveSkipped, 2)
        self.assertIn("şğüöçı İ Türkçe karakter", res.text)  # cp1254 doğru çözüldü
        self.assertIn("şğüöçı UTF-8", res.text)
        self.assertNotIn("binary", res.text)

    def testUploads(self):
        proj = self.work / "belgeler"
        proj.mkdir()
        (proj / "rapor.pdf").write_bytes(b"%PDF-1.4 sahte")
        (proj / "sema.png").write_bytes(b"\x89PNG sahte")
        (proj / "not.md").write_text("metin not", encoding="utf-8")
        self.store.AddSource(self.tid, proj)
        res = core.BuildPack(self.store, self.tid, core.PackOptions())
        self.assertEqual(sorted(res.uploads), ["rapor.pdf", "sema.png"])
        self.assertIn("rapor.pdf", res.text)
        self.assertNotIn("PDF-1.4", res.text)
        folder, copied = core.StageUploads(self.store, self.tid)
        self.assertEqual(sorted(gg.name for gg in copied), ["rapor.pdf", "sema.png"])
        self.assertTrue(all(gg.exists() for gg in copied))
        self.assertTrue(str(folder).startswith(_TMP))

    def testDisabledAndMissingSource(self):
        self.store.AddSource(self.tid, self.work / "yok_boyle_klasor")
        proj = self.MakeFiles(1, 500)
        res = core.BuildPack(self.store, self.tid, core.PackOptions())
        self.assertEqual(len(res.missingSources), 1)
        for s in self.store.ListSources(self.tid): self.store.SetSourceEnabled(s["id"], False)
        res2 = core.BuildPack(self.store, self.tid, core.PackOptions())
        self.assertEqual(res2.filesIncluded, [])
        self.assertEqual(res2.missingSources, [])

    #################### özet isteği / içe aktarma

    def testSummaryRoundtrip(self):
        self.store.AddEntry(self.tid, "Claude", "Veritabanı olarak SQLite seçtik.")
        req = core.BuildSummaryRequest(self.store, self.tid)
        self.assertIn("HEDEF:", req)
        self.assertIn("SQLite seçtik", req)
        answer = (
            "Tabii, işte özet:\n\n"
            "**HEDEF:** Çoklu yapay zeka bağlam aracını bitirmek\n\n"
            "**ÖZET:** Uygulama PySide6 ile yazılıyor.\nVeriler SQLite'ta tutuluyor.\n\n"
            "## KARARLAR\n- SQLite kullanılacak\n- Arayüz Qt olacak\n\n"
            "AÇIK İŞLER:\n1. Fark modunu test et\n2. PyInstaller ile exe\n  hazırla\n"
        )
        parsed = core.ParseSummaryResponse(answer)
        self.assertEqual(parsed["goal"], "Çoklu yapay zeka bağlam aracını bitirmek")
        self.assertIn("PySide6", parsed["summary"])
        self.assertIn("SQLite'ta", parsed["summary"])
        self.assertEqual(parsed["decisions"], ["SQLite kullanılacak", "Arayüz Qt olacak"])
        self.assertEqual(parsed["open"], ["Fark modunu test et", "PyInstaller ile exe hazırla"])
        counts = core.ApplySummary(self.store, self.tid, parsed)
        self.assertEqual((counts["decisions"], counts["open"]), (2, 2))
        again = core.ApplySummary(self.store, self.tid, parsed)   # tekrar: çift kayıt yok
        self.assertEqual((again["decisions"], again["open"]), (0, 0))
        self.assertEqual(len(self.store.ListItems(self.tid)), 4)
        self.assertEqual(self.store.GetTopic(self.tid)["goal"], "Çoklu yapay zeka bağlam aracını bitirmek")

    def testParseGarbage(self):
        p = core.ParseSummaryResponse("alakasız bir metin\nbaşka satır")
        self.assertEqual(p, {"goal": "", "summary": "", "decisions": [], "open": []})


class SitesAndMiscTests(unittest.TestCase):
    def setUp(self): self.store = core.Store(Path(_TMP) / f"s_{self._testMethodName}.db")

    def tearDown(self): self.store.close()

    def testDefaultSitesSeededOnce(self):
        self.store.EnsureDefaultSites()
        self.assertEqual([gg["name"] for gg in self.store.ListSites()], ["Claude", "ChatGPT", "Gemini"])
        for s in self.store.ListSites(): self.store.DeleteSite(s["id"])
        self.store.EnsureDefaultSites()          # kullanıcı sildiyse yeniden eklenmez
        self.assertEqual(self.store.ListSites(), [])

    def testSiteCrud(self):
        sid = self.store.AddSite("Claude 2", "https://claude.ai", "Claude")
        self.assertEqual(self.store.GetSite(sid)["name"], "Claude 2")
        self.store.UpdateSite(sid, "Claude iş", "https://claude.ai/new", "Claude")
        s = self.store.GetSite(sid)
        self.assertEqual((s["name"], s["url"]), ("Claude iş", "https://claude.ai/new"))
        self.store.DeleteSite(sid)
        self.assertIsNone(self.store.GetSite(sid))

    def testMeta(self):
        self.assertEqual(self.store.GetMeta("tema", "koyu"), "koyu")
        self.store.SetMeta("tema", "acik")
        self.store.SetMeta("tema", "koyu2")
        self.assertEqual(self.store.GetMeta("tema"), "koyu2")

    def testNormalizeUrl(self):
        n = core.NormalizeUrl
        self.assertEqual(n("claude.ai"), "https://claude.ai")
        self.assertEqual(n(" https://chatgpt.com/ "), "https://chatgpt.com/")
        self.assertEqual(n("http://localhost:8080"), "http://localhost:8080")
        for bad in ("", "   ", "javascript:alert(1)", "javascript:alert(document.domain)",
                    "file:///etc/passwd", "ftp://x.com", "iki kelime", "sadece", "https://user@evil.com"):
            self.assertEqual(n(bad), "", bad)

    def testCleanupProfiles(self):
        import shutil
        root = Path(_TMP) / "profiles"
        shutil.rmtree(root, ignore_errors=True)
        a = self.store.AddSite("A", "https://a.com", "Claude")
        b = self.store.AddSite("B", "https://b.com", "Gemini")
        for name in (f"site_{a}", f"site_{b}", "site_9999", "baska_klasor"): (root / name / "data").mkdir(parents=True)
        self.store.MarkProfileWipe(b)
        removed = core.CleanupProfiles(self.store)
        self.assertEqual(sorted(removed), sorted([f"site_{b}", "site_9999"]))
        self.assertTrue((root / f"site_{a}").exists())
        self.assertTrue((root / "baska_klasor").exists())      # bize ait olmayan klasöre dokunulmaz
        self.assertEqual(core.CleanupProfiles(self.store), [])  # işaretler temizlendi

    def testCleanSelection(self): self.assertEqual(core.CleanSelection("  a b c  "), "a\nb c")

    def testThemeTokens(self):
        import baglam_theme as th
        self.assertEqual(set(th.DARK), set(th.LIGHT))
        for name in th.THEMES:
            qss = th.BuildQss(name)
            self.assertNotIn("@", qss)
            self.assertIn(th.THEMES[name]["accent"], qss)


class SummaryFlowTests(unittest.TestCase):
    GOOD = "**HEDEF:** A\n\n**ÖZET:** B\n\n## KARARLAR\n- C\n\nAÇIK İŞLER:\n- D\n"

    def setUp(self):
        self.store = core.Store(Path(_TMP) / f"sf_{self._testMethodName}.db")
        self.tid = self.store.CreateTopic("Konu")

    def tearDown(self): self.store.close()

    def testAddChromiumFlag(self):
        self.assertEqual(core.AddChromiumFlag("", "--force-dark-mode"), "--force-dark-mode")
        self.assertEqual(core.AddChromiumFlag("--foo=1", "--force-dark-mode"), "--foo=1 --force-dark-mode")
        self.assertEqual(core.AddChromiumFlag("--force-dark-mode", "--force-dark-mode"), "--force-dark-mode")

    def testLooksLikeSummary(self):
        self.assertTrue(core.LooksLikeSummary(self.GOOD))
        self.assertTrue(core.LooksLikeSummary("```\n" + self.GOOD + "```"))
        self.assertFalse(core.LooksLikeSummary("Merhaba.\nHedef kitle gençler.\nÖzet: kısaca evet."))
        self.assertFalse(core.LooksLikeSummary(core.BuildInlineSummaryPrompt(self.store, self.tid)))
        self.assertFalse(core.LooksLikeSummary(core.BuildSummaryRequest(self.store, self.tid)))
        self.assertFalse(core.LooksLikeSummary(""))

    def testFencedReplyParses(self):
        p = core.ParseSummaryResponse("```text\nHEDEF: A\nÖZET: B\nKARARLAR:\n- C\nAÇIK İŞLER:\n- D\n```")
        self.assertEqual((p["goal"], p["summary"], p["decisions"], p["open"]), ("A", "B", ["C"], ["D"]))

    def testInlinePrompt(self):
        p0 = core.BuildInlineSummaryPrompt(self.store, self.tid)
        self.assertIn("HEDEF:", p0)
        self.assertIn("dosyaların adlarını", p0)
        self.assertNotIn("kayıtlı bağlam", p0)            # boş konuda birleştirme bölümü yok
        self.store.UpdateTopic(self.tid, goal="Eski hedef", summary="Eski özet")
        self.store.AddItem(self.tid, "decision", "SQLite kullanılacak")
        self.store.AddItem(self.tid, "open", "Test yaz")
        p1 = core.BuildInlineSummaryPrompt(self.store, self.tid)
        for s in ("kayıtlı bağlam", "Eski hedef", "Eski özet", "SQLite kullanılacak", "Test yaz", "BİRLEŞTİR"):
            self.assertIn(s, p1)

    def testInlinePromptIsBounded(self):
        self.store.UpdateTopic(self.tid, summary="x" * 50000)
        self.assertLess(core.EstimateTokens(core.BuildInlineSummaryPrompt(self.store, self.tid)), 3000)

    def testTranscriptPrompt(self):
        transcript = "Kullanıcı: merhaba\nYapay zeka: selam\n" * 10
        p = core.BuildTranscriptSummaryPrompt(self.store, self.tid, transcript)
        for s in ("HEDEF:", "=== SOHBET METNİ BAŞLANGIÇ ===", "=== SOHBET METNİ BİTİŞ ===",
                  "Kullanıcı: merhaba", "yok say", "dosyaların adlarını"):
            self.assertIn(s, p)
        self.assertNotIn("kayıtlı bağlam", p)
        self.assertFalse(core.LooksLikeSummary(p))
        self.store.UpdateTopic(self.tid, goal="Eski hedef", summary="Eski özet")
        p2 = core.BuildTranscriptSummaryPrompt(self.store, self.tid, transcript)
        for s in ("kayıtlı bağlam", "Eski özet", "aşağıdaki sohbet metniyle"): self.assertIn(s, p2)
        self.assertLess(p2.index("HEDEF:"), p2.index("=== SOHBET METNİ BAŞLANGIÇ ==="))  # istem önce, metin sonra

    def testCleanPageText(self):
        raw = "Başlık   \n\n\n  satır bir   \nsatır iki\r\n"
        self.assertEqual(core.CleanPageText(raw), "Başlık\n\n  satır bir\nsatır iki")
        long = "BASLANGIC" + "x" * 300000 + "SON"
        out = core.CleanPageText(long, maxChars=1000)
        self.assertLessEqual(len(out), 1000 + 60)
        self.assertIn("BASLANGIC", out)
        self.assertTrue(out.endswith("SON"))
        self.assertIn("kısaltıldı", out)
        self.assertEqual(core.CleanPageText(""), "")

    def testThemeIsBurgundyAndReadable(self):
        import baglam_theme as th

        def rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[gg:gg + 2], 16) for gg in (0, 2, 4))

        for name, c in th.THEMES.items():
            ar, ag, ab = rgb(c["accent"])
            self.assertTrue(ar > ag and ar > ab, f"{name}: vurgu rengi bordo/kırmızı tonlu değil")
            for key in ("bg", "surface", "surface2", "border", "select"):
                r, g, b = rgb(c[key])
                self.assertGreaterEqual(r, b, f"{name}.{key}: mavi tonlu")
            self.assertGreaterEqual(th.ContrastRatio(c["text"], c["bg"]), 7, name)
            self.assertGreaterEqual(th.ContrastRatio(c["text"], c["surface"]), 7, name)
            self.assertGreaterEqual(th.ContrastRatio(c["text"], c["select"]), 4.5, name)
            self.assertGreaterEqual(th.ContrastRatio(c["muted"], c["surface"]), 4.5, name)
            self.assertGreaterEqual(th.ContrastRatio(c["accent_text"], c["accent"]), 4.5, name)


class FileFlowTests(unittest.TestCase):
    def setUp(self):
        self.store = core.Store(Path(_TMP) / f"ff_{self._testMethodName}.db")
        self.tid = self.store.CreateTopic("Dosya Konusu")
        self.work = Path(tempfile.mkdtemp(prefix="bk_ff_"))

    def tearDown(self): self.store.close()

    def _project(self):
        proj = self.work / "proje"
        proj.mkdir()
        (proj / "a.py").write_text("print('a')\n", encoding="utf-8")
        (proj / "b.md").write_text("# not\nAPI_KEY=sk-abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
        (proj / "rapor.pdf").write_bytes(b"%PDF-1.4 sahte")
        (proj / "sema.png").write_bytes(b"\x89PNG sahte")
        (proj / ".env").write_text("GIZLI=1", encoding="utf-8")
        for i, name in enumerate(["a.py", "b.md", "rapor.pdf", "sema.png"]):
            os.utime(proj / name, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))  # sema.png en yeni
        self.store.AddSource(self.tid, proj)
        return proj

    #################### sekme sırası

    def testSiteOrderPersists(self):
        a = self.store.AddSite("A", "https://a.com", "Claude")
        b = self.store.AddSite("B", "https://b.com", "ChatGPT")
        c = self.store.AddSite("C", "https://c.com", "Gemini")
        self.assertEqual([gg["name"] for gg in self.store.ListSites()], ["A", "B", "C"])
        self.store.SaveSiteOrder([c, a, b])
        self.assertEqual([gg["name"] for gg in self.store.ListSites()], ["C", "A", "B"])
        d = self.store.AddSite("D", "https://d.com", "Diğer")          # yeni sekme sona eklenir
        self.assertEqual([gg["name"] for gg in self.store.ListSites()], ["C", "A", "B", "D"])
        self.store.DeleteSite(a)                                        # silinen sıradan çıkar
        self.assertEqual([gg["name"] for gg in self.store.ListSites()], ["C", "B", "D"])
        self.store.SetMeta("site_order", "bozuk json")                  # bozuk kayıt çökertmez
        self.assertEqual(len(self.store.ListSites()), 3)

    #################### seçilebilir dosyalar

    def testListSelectableFiles(self):
        self._project()
        items = core.ListSelectableFiles(self.store, self.tid)
        names = [gg.display for gg in items]
        self.assertEqual(names, ["proje/sema.png", "proje/rapor.pdf", "proje/b.md", "proje/a.py"])  # yeniden eskiye
        self.assertNotIn("proje/.env", names)                                                      # hassas yok
        kinds = {gg.display: gg.kind for gg in items}
        self.assertEqual((kinds["proje/a.py"], kinds["proje/rapor.pdf"]), ("text", "upload"))
        self.assertTrue(all(gg.size > 0 for gg in items))
        for s in self.store.ListSources(self.tid):                                               # kapalı kaynak
            self.store.SetSourceEnabled(s["id"], False)
        self.assertEqual(core.ListSelectableFiles(self.store, self.tid), [])

    def testBuildFilesText(self):
        self._project()
        items = core.ListSelectableFiles(self.store, self.tid)
        text, included, skipped = core.BuildFilesText(items)
        self.assertEqual(sorted(included), ["proje/a.py", "proje/b.md"])
        self.assertEqual(sorted(skipped), ["proje/rapor.pdf", "proje/sema.png"])
        self.assertIn("#### proje/a.py", text)
        self.assertIn("print('a')", text)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", text)       # maskelendi
        raw, _, _ = core.BuildFilesText(items, maskFlag=False)
        self.assertIn("sk-abcdefghijklmnopqrstuvwxyz123456", raw)
        empty, inc, _ = core.BuildFilesText([gg for gg in items if gg.kind == "upload"])
        self.assertEqual((empty, inc), ("", []))
        small, inc2, skip2 = core.BuildFilesText(items, maxTotalChars=60)
        self.assertTrue(any("boyut sınırı" in gg for gg in skip2))
        self.assertEqual(core.FormatSize(1536), "1,5 KB")

    #################### zip parçaları

    def testZipPartsRespectLimit(self):
        import zipfile
        d = self.work / "zip"
        d.mkdir()
        data = {}
        for i in range(6):                                   # sıkışmayan (rastgele) 20 KB'lık altı dosya
            data[f"r{i}.bin"] = os.urandom(20_000)
        data["sikisan.txt"] = b"a" * 200_000                 # sıkışan: zip içinde çok küçük
        data["dev.bin"] = os.urandom(80_000)                 # tek başına sınırı aşar
        items = []
        for name, blob in data.items():
            (d / name).write_bytes(blob)
            items.append((d / name, f"klasor/{name}"))
        limit = 50_000
        built = core.BuildZipParts(items, self.work / "out", "deneme", maxBytes=limit)
        self.assertGreaterEqual(len(built), 4)
        for b in built:
            if not b["oversize"]: self.assertLessEqual(b["size"], limit, b["path"].name)
        self.assertEqual([gg["path"].name for gg in built if gg["oversize"]], [gg["path"].name for gg in built if "dev.bin" in
                         zipfile.ZipFile(gg["path"]).namelist()[0]])
        self.assertEqual(sum(1 for gg in built if gg["oversize"]), 1)
        seen = {}
        for b in built:
            with zipfile.ZipFile(b["path"]) as zf:
                for n in zf.namelist():
                    self.assertNotIn(n, seen)                # hiçbir dosya iki kez yok
                    seen[n] = zf.read(n)
        self.assertEqual(sorted(seen), sorted(f"klasor/{gg}" for gg in data))
        for name, blob in data.items(): self.assertEqual(seen[f"klasor/{name}"], blob)    # içerik birebir
        self.assertTrue(built[0]["path"].name.startswith("deneme_01"))
        one = core.BuildZipParts(items[:1], self.work / "out2", "tek", maxBytes=limit)
        self.assertEqual(one[0]["path"].name, "tek.zip")      # tek parça: numarasız

    def testUniqueArcnames(self):
        pairs = [(Path("x/a.txt"), "p/a.txt"), (Path("y/a.txt"), "p/a.txt"), (Path("z/b"), "b"), (Path("w/b"), "b")]
        arcs = [a for _, a in core._uniqueArcnames(pairs)]
        self.assertEqual(len(set(gg.lower() for gg in arcs)), 4)
        self.assertEqual(arcs[0], "p/a.txt")

    def testPrepareAttachments(self):
        self._project()
        items = core.ListSelectableFiles(self.store, self.tid)
        uploads = [gg for gg in items if gg.kind == "upload"]
        one = core.PrepareAttachments(uploads[:1], "Dosya Konusu")
        self.assertEqual((one.paths, one.zippedFlag), ([uploads[0].path], False))      # tek dosya: özgün
        off = core.PrepareAttachments(items, "Dosya Konusu", zipPartsFlag=False)
        self.assertEqual(len(off.paths), 4)                                         # zip kapalı: özgün dosyalar
        att = core.PrepareAttachments(items, "Dosya Konusu", zipPartsFlag=True)
        self.assertTrue(att.zippedFlag and len(att.paths) == 1 and att.paths[0].suffix == ".zip")
        self.assertTrue(str(att.folder).startswith(_TMP))
        import zipfile
        self.assertEqual(sorted(zipfile.ZipFile(att.paths[0]).namelist()),
                         ["proje/a.py", "proje/b.md", "proje/rapor.pdf", "proje/sema.png"])
        att2 = core.PrepareAttachments(items, "Dosya Konusu", zipPartsFlag=True)      # tekrar: klasör temizlenir
        self.assertEqual(len(list(att2.folder.iterdir())), 1)
        self.assertEqual(core.PrepareAttachments([], "x").paths, [])

    def testStageUploadsZip(self):
        import zipfile
        self._project()
        folder, files = core.StageUploads(self.store, self.tid, zipPartsFlag=True)
        self.assertEqual(len(files), 1)
        self.assertEqual(sorted(zipfile.ZipFile(files[0]).namelist()), ["proje/rapor.pdf", "proje/sema.png"])
        folder2, files2 = core.StageUploads(self.store, self.tid, zipPartsFlag=False)
        self.assertEqual(sorted(gg.name for gg in files2), ["rapor.pdf", "sema.png"])


class RelayTemplateTests(unittest.TestCase):
    def testRoundtripAndDefaults(self):
        txt = core.FormatRelayTemplates(core.DEFAULT_RELAY_TEMPLATES)
        self.assertEqual(core.ParseRelayTemplates(txt), core.DEFAULT_RELAY_TEMPLATES)

    def testParseAddsPlaceholderAndSkipsEmpty(self):
        got = core.ParseRelayTemplates("# A\nşunu yap\n\n# Boş\n\n# B\nx {metin} y\n")
        self.assertEqual(got, [("A", "şunu yap\n\n{metin}"), ("B", "x {metin} y")])

    def testApplyKeepsBraces(self): self.assertEqual(core.ApplyRelayTemplate("Sor: {metin}", "f(x){a}"), "Sor: f(x){a}")

    def testStoreFallbackAndSave(self):
        with tempfile.TemporaryDirectory() as d, contextlib.closing(core.Store(Path(d) / "x.db")) as st:   # Windows açık veritabanı dosyasını silemez
            self.assertEqual(core.GetRelayTemplates(st), core.DEFAULT_RELAY_TEMPLATES)
            core.SaveRelayTemplates(st, [("Tek", "Bak: {metin}")])
            self.assertEqual(core.GetRelayTemplates(st), [("Tek", "Bak: {metin}")])
            core.SaveRelayTemplates(st, [])
            self.assertEqual(core.GetRelayTemplates(st), core.DEFAULT_RELAY_TEMPLATES)


class ChatsDropTranslateTests(unittest.TestCase):
    def testIsChatUrl(self):
        self.assertTrue(core.IsChatUrl("https://claude.ai/chat/abc"))
        self.assertTrue(core.IsChatUrl("https://gemini.google.com/app/123"))
        self.assertFalse(core.IsChatUrl("https://claude.ai/"))
        self.assertFalse(core.IsChatUrl("https://claude.ai/new"))
        self.assertFalse(core.IsChatUrl("about:blank"))

    def testRecordListRemove(self):
        with tempfile.TemporaryDirectory() as d, contextlib.closing(core.Store(Path(d) / "x.db")) as st:   # Windows açık veritabanı dosyasını silemez
            tid = st.CreateTopic("T")
            self.assertFalse(core.RecordChat(st, tid, 1, "https://claude.ai/"))
            for i in range(12): core.RecordChat(st, tid, 1, f"https://claude.ai/chat/{i}", f"Sohbet {i}", now=1000 + i)
            got = core.ListChats(st, tid, 10)
            self.assertEqual(len(got), 10)
            self.assertEqual(got[0]["url"], "https://claude.ai/chat/11")
            core.RecordChat(st, tid, 1, "https://claude.ai/chat/3", "", now=2000)   # başlık korunur, en üste çıkar
            top = core.ListChats(st, tid, 10)[0]
            self.assertEqual((top["url"], top["title"]), ("https://claude.ai/chat/3", "Sohbet 3"))
            core.RemoveChat(st, tid, 1, "https://claude.ai/chat/3")
            self.assertNotIn("https://claude.ai/chat/3", [gg["url"] for gg in core.ListChats(st, tid, 50)])
            self.assertEqual(core.ListChats(st, tid + 99), [])

    def testItemsFromPaths(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sub").mkdir()
            (d / "sub" / "a.py").write_text("x", encoding="utf-8")
            (d / "r.pdf").write_bytes(b"%PDF")
            (d / ".env").write_text("K=1", encoding="utf-8")
            items, sens = core.ItemsFromPaths([d / "sub", d / "r.pdf", d / ".env", d / "r.pdf"])
            self.assertEqual(sorted((gg.display, gg.kind) for gg in items), [("r.pdf", "upload"), ("sub/a.py", "text")])
            self.assertEqual(sens, 1)

    def testTranslateHelpers(self):
        self.assertEqual(core.GuessTargetLang("This is an English sentence."), "tr")
        self.assertEqual(core.GuessTargetLang("Bu bir Türkçe cümle ve çok güzel"), "en")
        url, cut = core.TranslateUrl("hello world & more", "tr")
        self.assertIn("sl=auto&tl=tr&text=hello%20world%20%26%20more", url)
        self.assertFalse(cut)
        url, cut = core.TranslateUrl("a" * 5000, "en")
        self.assertTrue(cut)
        self.assertLess(len(url), 2200)

    def testLastReply(self):
        self.assertIn('[data-message-author-role="assistant"]', core.LastReplySelectors("https://chatgpt.com/c/1"))
        self.assertTrue(core.LastReplySelectors("https://gemini.google.com/app/1"))
        self.assertEqual(core.LastReplySelectors("https://example.org/x"), [])
        js = core.LastReplyJs(['a"b', "c"])
        self.assertIn('"a\\"b"', js)
        self.assertTrue(js.startswith("(function(sels){"))


class ShortcutTests(unittest.TestCase):
    def testScriptEscapesAndTargets(self):
        import baglam_shortcut as sc
        js = sc.BuildScript(Path("C:/Users/O'Neil/Start/ggContext.lnk"), "C:/Apps/O'Neil/ggContext.exe")
        self.assertIn("O''Neil", js)
        self.assertIn("$s.TargetPath = 'C:/Apps/O''Neil/ggContext.exe'", js)
        self.assertIn("CreateShortcut(", js)

    def testNotCreatedOutsideFrozenWindows(self):
        import baglam_shortcut as sc
        self.assertFalse(sc.EnsureStartMenuShortcut(None))

if __name__ == "__main__": unittest.main(verbosity=2)
