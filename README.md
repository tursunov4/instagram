# Arzoni qayerda? — kunlik Reels avtomati

Har kuni soat 19:00 da (Toshkent vaqti) tizim o'zi:

1. narxtahlil.uz/supermarkets/ sahifasidan eng so'nggi supermarket narxlarini oladi;
2. bu hafta hali ko'rsatilmagan, narx farqi eng katta mahsulotni tanlaydi;
3. Claude orqali qisqa, sodda boshlanish va yakuniy gapni yozadi (narxlar esa shablondan olinadi, shuning uchun raqamda xato bo'lmaydi);
4. o'zbekcha AI ovoz qo'shadi (Microsoft: Madina yoki Sardor);
5. 1080×1920 video yasaydi (fon musiqasi ham o'zimiz sintez qilgan, mualliflik muammosi yo'q);
6. Instagram'ga Reels qilib chiqaradi.

Narxlar saytda haftada bir yangilanadi, shuning uchun har kuni boshqa mahsulot chiqadi. Yangi hafta narxlari kelganda ro'yxat qaytadan boshlanadi.

## O'rnatish (bir marta)

### 1. Fayllarni repoga joylash

Shu papkadagi hamma narsani (`.github` papkasi ham) `instagram` reposiga yuklang. Repo **ochiq (public)** qolishi kerak, chunki Instagram videoni shu yerdan oladi.

### 2. Instagram tokeni (bepul yo'l)

1. https://developers.facebook.com saytida yangi ilova (app) yarating, turi: Business.
2. Ilovaga "Instagram" mahsulotini qo'shing va "API setup with Instagram login" bo'limiga kiring.
3. @arzoni_qayerdaa akkauntini qo'shib, token yarating. Kerakli ruxsatlar: `instagram_business_basic`, `instagram_business_content_publish`.
4. Agar so'ralsa, akkauntni ilovaning "Instagram testers" ro'yxatiga qo'shib, Instagram ilovasida taklifni qabul qiling.

Akkaunt professional (Business yoki Creator) bo'lishi shart. Batafsil: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login

### 3. GitHub tokeni (Instagram tokenini avtomatik yangilash uchun)

Instagram tokeni 60 kun yashaydi. Tizim uni har gal yangilab, o'zi saqlab qo'yadi. Buning uchun GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token:

- Repository access: faqat `instagram`
- Permissions → Secrets: **Read and write**
- Muddati: iloji boricha uzoq

### 4. Kalitlarni kiritish

Repo → Settings → Secrets and variables → Actions → **New repository secret**:

| Nomi | Qiymati |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API kalitingiz |
| `IG_ACCESS_TOKEN` | 2-qadamdagi Instagram tokeni |
| `GH_PAT` | 3-qadamdagi GitHub tokeni |

### 5. Sinab ko'rish

1. Actions → **Kunlik Reels** → **Run workflow** (`dry_run` belgisi qo'yilgan holda).
2. Tugagach, sahifa pastidagi `reel-…` faylini yuklab oling va videoni ko'ring. Instagram'ga hech narsa chiqmaydi.
3. Hammasi yoqsa, `dry_run` belgisini olib, yana bir marta ishga tushiring: video Instagram'ga chiqadi.

Shundan keyin har kuni o'zi ishlaydi. Biror qadam xato bersa, GitHub emailingizga xabar yuboradi.

## Sozlamalar

- **Vaqt**: `.github/workflows/kunlik-reels.yml` dagi `cron: "0 14 * * *"` (UTC vaqtida). Masalan 20:00 uchun `"0 15 * * *"`. GitHub ba'zan 5–20 daqiqa kechiktiradi.
- **Ovoz**: Settings → Variables → `TTS_VOICE` = `uz-UZ-SardorNeural` (erkak ovozi). Standart: `uz-UZ-MadinaNeural` (ayol).
- **Logotip**: `assets/logo.png` (shaffof fonli PNG) qo'ysangiz, videoda chizilgan logo o'rniga o'sha chiqadi.
- **Metricool orqali** (faqat Advanced tarifda): Variables → `PUBLISHER` = `metricool`, Secret → `METRICOOL_TOKEN`.
- **Zaxira ovoz**: bepul ovoz xizmati ishlamay qolsa, Azure Speech kalitini `AZURE_SPEECH_KEY` (secret) va hududini `AZURE_SPEECH_REGION` (variable) qilib qo'shing.

## Xavfsizlik to'ri

- Sayt ochilmasa, oxirgi saqlangan narxlar ishlatiladi (`data/latest.json`).
- Claude javob bermasa yoki qoidaga zid gap yozsa, tayyor shablon gaplar ishlatiladi.
- Ovoz yaratilmasa, video musiqa va yozuvlar bilan baribir chiqadi.
- Bir kunda ikki marta chiqib ketmaydi (`data/state.json`).

## Qo'lda ishga tushirish (kompyuterda)

```bash
pip install -r requirements.txt
python reels/main.py --dry-run              # video out/ papkaga tushadi
python reels/main.py --dry-run --product qiyma
```
