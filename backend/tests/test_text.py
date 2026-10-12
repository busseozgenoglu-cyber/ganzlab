from app.colloquial import colloquial_tr
from app.emotion import infer_emotion, parse_tagged_text, resolve
from app.engine import split_text
from app.textnorm import normalize, tr_int_to_words, tr_ordinal


def test_numbers():
    assert tr_int_to_words(1250) == "bin iki yüz elli"
    assert tr_int_to_words(2026) == "iki bin yirmi altı"
    assert tr_int_to_words(0) == "sıfır"
    assert tr_ordinal(4) == "dördüncü"
    assert tr_ordinal(21) == "yirmi birinci"


def test_normalize_tr():
    out = normalize("Fiyatı 1.250 TL, %20 indirimle 999,90 ₺. Randevu 12.10.2026 saat 14:30.", "tr")
    assert "bin iki yüz elli lira" in out
    assert "yüzde yirmi" in out
    assert "dokuz yüz doksan dokuz virgül doksan lira" in out
    assert "on iki ekim iki bin yirmi altı" in out
    assert "on dört otuz" in out
    assert normalize("Dr. Ayşe 3. katta, 5 km koştu.", "tr") == "doktor Ayşe üçüncü katta, beş kilometre koştu."
    assert "İlevın Labs" in normalize("ElevenLabs yerine", "tr")
    assert "Yutub" in normalize("YouTube kanalı", "tr")


def test_normalize_cleanup():
    assert normalize("Merhaba!!! Nasılsın?? — iyi (sanırım)… 🎉", "tr") == "Merhaba! Nasılsın? iyi, sanırım..."


def test_colloquial():
    assert colloquial_tr("Yarın geleceğim, sana bir şey göstereceğim.") == "Yarın gelicem, sana bişey göstericem."
    assert colloquial_tr("Ne yapacaksın? Hiçbir şey yapmayacağım.") == "Napıcaksın? Hiçbişey yapmıycam."
    assert colloquial_tr("olacak, görecek, bulacağız, olmayacak") == "olucak, görücek, bulucaz, olmıycak"
    assert colloquial_tr("Gelecek yıl yiyecek alacak mısın?") == "Gelecek yıl yiyecek alıcak mısın?"
    assert colloquial_tr("değil mi") == "di mi"


def test_tags():
    segs = parse_tagged_text("[heyecanlı] Selam! [gülme] Devam. [nefes] [üzgün] Bitti. [bilinmeyen] Son.")
    assert [s.emotion for s in segs] == ["heyecanlı", "üzgün"]
    assert segs[1].text == "Bitti. Son."
    assert segs[0].text == "Selam! Hahaha! Devam."
    assert segs[1].pause_before_ms == 500
    assert resolve("EXCITED").name == "heyecanlı"
    assert resolve("normal").name == "normal"
    assert resolve("yok") is None


def test_auto_emotion():
    assert infer_emotion("Bu harika bir haber!") == "heyecanlı"
    assert infer_emotion("Maalesef kaybettik.") == "üzgün"
    assert infer_emotion("Yarın geliyorum.") is None


def test_split_text():
    text = "[heyecanlı] Selam! Bugün güzel bir gün. Hazır mısın?\n\nYeni paragraf. " + "Uzun bir cümle, " * 20 + "bitti."
    chunks = split_text(text, 170, normalizer=lambda s: s)
    assert all(len(c.text) <= 170 for c in chunks)
    assert chunks[0].emotion == "heyecanlı"
    assert chunks[0].punct == "?"
    assert any(c.pause_after_ms >= 650 for c in chunks)  # paragraf duraklaması
    assert "".join(c.text for c in chunks).count("bitti") == 1
