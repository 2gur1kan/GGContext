# ggContext

[English](README.md) · **Türkçe**

Claude, ChatGPT, Gemini gibi yapay zeka sitelerini **tek pencerede, ayrı sekmelerde** açıp kullanmanı sağlayan ve
aralarında **bağlamı (özet, kararlar, cevaplar, dosyalar) birkaç tıkla taşıyan** yerel bir Windows uygulaması.
Ücretsiz hesaplarla çalışırken bir sohbetin kotası dolduğunda işi diğerinde, konuyu kaybetmeden ve az token harcayarak
sürdürmek için yapıldı.

> **Önemli:** ggContext senin yerine mesaj göndermez, hesaplar arasında kendi başına geçiş yapmaz ve şifre saklamaz.
> Sitelere sen giriş yaparsın; uygulama yalnızca kopyala-yapıştır işini kolaylaştırır. Mesajı göndermek (Enter) her zaman sana kalır.

<p align="center"><img src="ggcontext.png" alt="ggContext simgesi" width="96"></p>

## Neler yapar?

- **Tek pencerede çok sekme:** Claude, ChatGPT, Gemini (ve istediğin başka siteler) gerçek birer tarayıcı sekmesi olarak açılır. Her sekmenin kendi giriş oturumu vardır.
- **Konular:** Bir projeye ait hedef, özet, kararlar, açık işler, cevaplar ve dosyalar tek bir "konu" altında tutulur.
- **Bağlam paketi:** Konunun özeti, kararları, son cevapları ve dosyaları token bütçesine göre kısaltılarak tek parça hâline getirilir ve açık sohbetin mesaj kutusuna yapıştırılır.
- **Bağlam çıkarma:** Açık sohbetin metni okunup (ör. Gemini'ye) özetletilir; cevap konuya otomatik işlenir.
- **Dosyaları sohbete ekleme:** Konuya eklediğin dosyalardan seçtiklerini, istediğin an açık sohbete metin ya da dosya olarak ekler; çok dosya 30 MB'lık zip parçalarına sarılır.
- **Sekmeler arası soru:** Seçtiğin metni sağ tıkla başka bir sekmeye hazır istemlerle gönderirsin.
- **Çeviri kutusu:** Seçili metni Google Çeviri'de küçük bir kutuda açar.
- **Koyu/açık bordo tema**, sürüklenebilir ve adı değiştirilebilir sekmeler, görev çubuğu ve bildirim alanı simgesi, Windows aramasında görünme.

## Gereksinimler

| Ne | Sürüm | Not |
|---|---|---|
| İşletim sistemi | Windows 10 / 11 (64 bit) | Başlık çubuğu rengi Windows 11'de tam uygulanır |
| Python | 3.10 veya üstü (öneri: 3.12) | Çekirdek yalnızca standart kütüphaneyi kullanır |
| PySide6 | 6.8 veya üstü | Qt arayüzü ve gömülü tarayıcı (QtWebEngine), `requirements.txt` |
| PyInstaller | 6.0 veya üstü | Yalnızca `.exe` üretmek için, `requirements-build.txt` |
| İnternet | Gerekli | Paketleri kurmak ve yapay zeka sitelerine bağlanmak için |

PySide6 büyük bir pakettir (yüzlerce MB). Gömülü tarayıcı Chromium tabanlı olduğu için çıkan `.exe` klasörü de büyüktür.

## Kurulum

### A) `.exe` olarak (önerilen)

1. Projeyi indir ya da klonla: `git clone <depo-adresi>`
2. Klasördeki **`build.bat`** dosyasına çift tıkla.
   Betik Python'u bulur, testleri çalıştırır, gerekirse `.venv` içine PySide6 ve PyInstaller'ı kurar, sonra uygulamayı derler.
3. Bittiğinde **`dist\ggContext\ggContext.exe`** oluşur. Başka yere taşırken `dist\ggContext` klasörünün **tamamını** taşı.

İlk açılışta uygulama Başlat menüsüne bir kısayol bırakır; sonra Windows tuşuna basıp **ggContext** yazarak bulabilirsin.

### B) Python ile çalıştırmak

```
pip install -r requirements.txt
python main.py
```

### Elle `.exe` üretmek

```
pip install -r requirements-build.txt
pyinstaller --noconfirm --clean --noconsole --onedir --icon ggcontext.ico --name ggContext main.py
```

### Testler

```
python -m unittest test_core
```

## Verilerin nerede durur?

Konuların, kaydedilen cevapların ve ayarların `%APPDATA%\ggContext\` altındadır (`baglam.db`). Sekmelerin giriş oturumları aynı yerdeki
`profiles\` klasöründedir. Uygulama klasörünü arkadaşınla paylaşırsan bu veriler **gitmez**. Eski sürümün `BaglamKoprusu` klasörü varsa ilk açılışta
otomatik `ggContext`'e taşınır.

> `profiles\` klasörü giriş çerezlerini şifrelenmemiş tutar. Bu klasörü kimseyle paylaşma, GitHub'a yükleme.

## Günlük kullanım

1. Soldan bir **konu** seç ya da **Yeni konu** oluştur. İlk açılışta Claude, ChatGPT ve Gemini sekmeleri hazır gelir; **Hesap / sekme ekle** ile başka site de ekleyebilirsin.
2. Bir sekmede sohbet et. Cevabı sitenin **Kopyala** düğmesiyle kopyalayınca, uygulama onu o sekmenin cevabı olarak konuya otomatik kaydeder.
3. Başka bir sekmeye geçmeden önce kaynak sekmede **Bağlamı çıkar**'a bas. Uygulama sohbetin metnini okur ve sağ paneldeki
   **Özet > Bağlamı çıkaracak sekme** olarak seçili sekmeye (varsayılan Gemini) özet isteğiyle yapıştırır. Enter'a sen basarsın; cevap gelince **Kopyala**'ya basarsın.
   Uygulama cevabın bir bağlam özeti olduğunu tanır ve konuya aktarılmasını önerir.
4. Diğer sekmede mesaj kutusuna bir kez tıkla ve **Bağlamı yapıştır**'a bas. İstersen **Paket** sekmesindeki **İstek** alanına sorunu yaz; bağlam ve soru tek seferde gider.
5. Konuya dosya eklediysen **Dosyaları ekle…** ile istediğin an seçtiklerini açık sohbete yapıştırabilirsin.

### Bağlam çıkarma nasıl çalışır?

- **Bağlamı çıkar (sekmedeki düğme):** Kaynak sekmedeki açık sohbetin metni sayfadan okunur ve seçili çıkarma sekmesine yapıştırılır. Metin başka bir hizmete gideceği için aktarmadan önce onay sorulur (sağ panelden kapatılabilir).
  Seçili sekme kaynağın kendisiyse istem aynı sohbet içinde istenir.
- **Bu sohbet içinde bağlam çıkar (⋯ menüsü):** Özeti, konuşmayı zaten bilen sohbetin kendi yapay zekasına yaptırır.
- Cevap `HEDEF:`, `ÖZET:`, `KARARLAR:`, `AÇIK İŞLER:` başlıklarından en az üçünü içeriyorsa tanınır.
- Okunan metin en fazla yaklaşık 80 bin karakterdir; fazlasının ortası kısaltılır. Sayfada görünmeyen eski mesajlar okunamaz.

### Paket neleri içerir?

Bütçe azaldıkça en alttaki katmandan başlayarak kısaltılır:

1. Başlık, hedef, özet
2. Kararlar ve açık işler (her zaman korunur)
3. Son konuşmalar (+ sabitlenmiş en fazla 3 eski cevap)
4. Dosyalar (en son değişenler öncelikli)

Ham kayıtlar veritabanında hiç silinmez; paket yalnızca bir görünümdür. **Fark modu** aynı sohbete devam ederken yalnızca değişenleri gönderir.
Token sayısı tahminidir (≈3,5 karakter = 1 token).

### Dosyaları sohbete ekleme

Konunun dosyalarından işaretlediklerini açık sohbete iki biçimde eklersin:

- **Metin olarak yapıştır:** içerik mesaj kutusuna gelir, parola benzeri değerler maskelenir.
- **Dosya olarak ekle:** PDF, görsel, Office dosyaları için. Birden fazla dosya ≤30 MB'lık zip parçalarına sarılır (kapatılabilir); 30 MB'ı aşan tek dosya kendi zip'ine girer ve uyarı verir.

Dosya kipinde dosyalar panoya "dosya" olarak konup sayfaya yapıştırılır. Bazı siteler bunu kabul etmeyebilir: mesaj kutusuna tıklayıp `Ctrl+V` yap ya da hazırlanan klasörden sürükle.
Dosya olarak eklenenlerde maskeleme yapılamaz.

### Sekmeler arası soru ve çeviri

- Sayfada metin seç, sağ tıkla: **Başka sekmeye sor > (sekme) > (şablon)**. Hazır şablonlar: olduğu gibi sor, web'de araştır, eleştir, özetle, Türkçeye çevir. Şablonlar soldaki **İstem şablonları** düğmesinden düzenlenir (`# Ad` satırı + istem, `{metin}` seçili metnin yeridir).
- **Çevir (Google Çeviri):** seçili metni küçük bir kutuda translate.google.com'da açar, kaynak dili Google algılar. Hedef otomatik seçilir (Türkçe metin İngilizceye, diğerleri Türkçeye).
- Sekme adının üzerine **dosya ya da metin sürükleyip bırakırsan** o sekmeye eklenir.

## Gizlilik ve güvenlik

- `.env`, `.pem`, `.key`, `id_rsa`, `credentials.json` gibi dosyalar asla pakete girmez.
- API anahtarı ve parola benzeri değerler (`sk-…`, `password = …`, `Bearer …`) maskelenir. Bu en iyi çabadır; göndermeden önce Paket sekmesindeki önizlemeye göz at.
- E-posta ve şifreler uygulamada saklanmaz; oturum tarayıcıdaki gibi çerezlerle yerel klasörde kalır.
- Çeviri ve "başka sekmeye sor" gibi işlemler seçtiğin metni ilgili siteye gönderir; yalnızca sen istediğinde çalışır.

## Bilinen sınırlar

- Siteler arayüzlerini değiştirebilir; **Son cevabı seç** gibi sayfa yapısına bağlı özellikler bu yüzden güncelleme isteyebilir.
- Bazı siteler (özellikle Google ile giriş) gömülü tarayıcıları engelleyebilir; e-posta/kod ile girişi dene.
- Koyu tema sekmelerdeki siteler için uygulama açılırken uygulanır; temayı değiştirince siteler için uygulamayı yeniden aç.
- Proje bağımsızdır; Anthropic, OpenAI veya Google ile resmî bir bağı yoktur.

## Dosya yapısı

| Dosya | Görev |
|---|---|
| `main.py` | Başlatıcı |
| `baglam_core.py` | Veritabanı, paket üretimi, token bütçesi, dosya/zip hazırlama, sekme ve sohbet kayıtları (yalnızca standart kütüphane) |
| `baglam_ui.py` | PySide6 arayüzü: gömülü web sekmeleri ve bağlam paneli |
| `baglam_theme.py` | Koyu/açık bordo tema ve Windows başlık çubuğu rengi |
| `baglam_icon.py` | Koda gömülü uygulama simgesi (siyah zemin üstüne bordo "G") |
| `baglam_shortcut.py` | Başlat menüsü kısayolu (Windows aramasında görünmek için) |
| `ggcontext.ico`, `ggcontext.png` | `.exe` simgesi ve README görseli |
| `test_core.py` | Çekirdek testleri |
| `build.bat` | Tek tıkla `.exe` üretimi |

## Kısayollar ve bölümler

### Klavye kısayolları

| Kısayol | Ne yapar |
|---|---|
| `Ctrl+1` | Soldaki sekmeye geç (başta ise sona sarar) |
| `Ctrl+2` | Sağdaki sekmeye geç (sonda ise başa sarar) |
| `Ctrl+B` | Sağdaki bağlam panelini aç/kapat |
| `Ctrl+Shift+B` | Soldaki konu panelini göster/gizle |
| `Ctrl+Shift+C` | Bağlam paketini panoya kopyala |
| `Ctrl+Shift+S` | Panodaki metni cevap olarak konuya ekle |
| `Ctrl+Shift+F` | Seçtiğin dosyaları açık sohbete ekle |
| `Ctrl+Shift+L` | Açık sohbetteki yapay zekanın son mesajını seç |
| `Ctrl+Shift+T` | Seçili metni Google Çeviri kutusunda aç |

### Sekmedeki düğmeler

| Düğme | Görevi |
|---|---|
| `←` `→` `↻` `⌂` | Geri, ileri, yenile, sitenin ana adresine dön (⌂) |
| Adres çubuğu | Sekmenin adresi; Enter ile gidersin |
| **Bağlamı çıkar** | Açık sohbeti okuyup sağ panelde seçili sekmeye özet isteğiyle yapıştırır |
| **Bağlamı yapıştır** | Konunun bağlam paketini bu sekmenin mesaj kutusuna yapıştırır |
| **Dosyaları ekle…** | Seçtiğin dosyaları bu sohbete metin ya da dosya/zip olarak ekler |
| **Son cevabı seç** | Sohbetteki son yapay zeka mesajını seçer |
| `⋯` menüsü | Bu sohbet içinde bağlam çıkar, seçili metni cevap olarak kaydet, yakınlaştırma, sayfayı zorla koyulaştır, adı değiştir, ad/adres düzenle, oturumu temizle, sekmeyi kaldır |

### Sağ tık menüleri

| Nerede | Seçenek |
|---|---|
| Sayfada (metin seçiliyken) | **Başka sekmeye sor**, **Çevir (Google Çeviri)**, **Seçili metni cevap olarak kaydet** |
| Sayfada (her zaman) | **ggContext** alt menüsü: bağlamı yapıştır, dosyaları ekle, bağlamı çıkar, son cevabı seç |
| Sekme adında | Adı değiştir, ad/adres düzenle, sekmeyi kaldır (çift tık da adı değiştirir) |

### Sağ panel sekmeleri

| Sekme | İçeriği |
|---|---|
| **Özet** | Bağlamı çıkaracak sekme seçimi, hedef, özet, kararlar, açık işler |
| **Cevaplar** | Kaydedilen cevaplar (sabitleme, silme) |
| **Dosyalar** | Konuya eklenen dosya/klasörler, "seçtiğim dosyaları açık sohbete ekle", zip seçeneği, yüklenecekler klasörü |
| **Sohbetler** | Konudaki son 10 sohbet; tıklayınca o sekmede açılır |
| **Paket** | Bağlam paketinin önizlemesi, katmanlar, fark modu, **İstek** alanı |

### Durum çubuğu ve simgeler

| Öğe | Görevi |
|---|---|
| `◧` (sağ alt) | Soldaki konu panelini gizle/göster |
| `▥` (sağ alt) | Sağdaki bağlam panelini aç/kapat |
| Görev çubuğu simgesi | Çalışan uygulama; sağ tık > "Görev çubuğuna sabitle" ile kalıcı yapabilirsin |
| Bildirim alanı simgesi | Tıklayınca pencereyi gizler/gösterir; menüde **Kapatınca tepsiye küçül**, **Windows aramasına ekle / yenile**, **Çık** |
| Sürükleme | Üstteki sekmeleri sürükleyerek sırala; sıra kaydedilir |

## Kod stili

Kod, kendi kod yazma stil rehberime uyarlandı: herkese açık işlev ve yöntemler PascalCase, yerel değişken, parametre ve alanlar camelCase,
bool bayraklar `...Flag` ile biter, geçici değişkenlerde `gg` kullanılır, tek işlik koşul ve metotlar tek satırdır, yorumlar Türkçe ve küçük harfle başlar.
Qt'nin adıyla çağırdığı yöntemler (`closeEvent`, `eventFilter` gibi) değiştirilmemiştir.
