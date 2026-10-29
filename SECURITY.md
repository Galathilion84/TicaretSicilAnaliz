# Güvenlik politikası / Security policy

## Güvenlik açığı bildirme
Bir güvenlik açığı bulduysanız **herkese açık issue açmayın**. Bunun yerine GitHub'ın
**"Report a vulnerability"** (Security → Advisories) özelliğiyle özel olarak bildirin. Mümkünse şunları ekleyin:
etkilenen sürüm, yeniden üretme adımları ve etkisi.

Found a vulnerability? Please do **not** open a public issue. Use GitHub's private
"Report a vulnerability" feature (Security → Advisories) instead.

## Kapsam
Bu uygulama **yalnızca kullanıcının kendi bilgisayarında** çalışacak şekilde tasarlanmıştır:

- Yalnızca `127.0.0.1`'de dinler; adres değiştirilemez.
- Yabancı `Host` ve farklı kaynaklı (`Origin`) istekleri reddeder (DNS rebinding / CSRF).
- TSG parolası ve Gemini anahtarı işletim sistemi kimlik kasasında saklanır (kasa yoksa `.env`).
- Sunucu yalnızca `https://www.ticaretsicil.gov.tr`'ye ve Gemini API'ye bağlanır.

Kapsam dışı: uygulamayı internete ya da yerel ağa açmak (örneğin ters vekil ile). Bu desteklenmez ve güvenli değildir,
çünkü uygulamada kullanıcı hesabı yoktur.

## Desteklenen sürümler
Yalnızca en son sürüm (`main`) güvenlik düzeltmesi alır.
