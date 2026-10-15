import json
import math
import sqlite3
import time

from config import ADMIN_ID, DB_PATH

con = sqlite3.connect(DB_PATH, check_same_thread=False)
con.row_factory = sqlite3.Row

CHEF_TYPES = {"baliq": "Baliqchi", "osh": "Osh pishiruvchi", "shorva": "Shorvachi",
              "salat": "Salatchi", "kabob": "Mangalchi", "bar": "Bar"}
CATS = {"food": "Taomlar", "drink": "Ichimliklar", "salad": "Salatlar"}
SUBS = {"food": ["Baliq taomlari", "Oshlar", "Suyuq ovqatlar", "Kabob va grill"],
        "drink": ["Gazli ichimliklar", "Suv va sharbat", "Choy"], "salad": ["Salatlar"]}
SUBCHEF = {"Baliq taomlari": "baliq", "Oshlar": "osh", "Suyuq ovqatlar": "shorva",
           "Kabob va grill": "kabob", "Gazli ichimliklar": "bar", "Suv va sharbat": "bar",
           "Choy": "bar", "Salatlar": "salat"}
DEFAULTS = {"card": "8600 1234 5678 9012", "card_owner": "Dasturxon restorani", "km_price": "3000",
            "cashback": "5", "ref_invite": "10", "ref_buyers": "5", "ref_min": "50000",
            "ayvon": "20", "xona": "10", "accepting": "1"}


def q(sql, args=()):
    return con.execute(sql, args).fetchall()


def one(sql, args=()):
    return con.execute(sql, args).fetchone()


def ex(sql, args=()):
    cur = con.execute(sql, args)
    con.commit()
    return cur.lastrowid


def get(key):
    r = one("SELECT v FROM settings WHERE k=?", (key,))
    return r["v"] if r else DEFAULTS.get(key, "")


def geti(key):
    return int(float(get(key) or 0))


def put(key, value):
    ex("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, str(value)))


def som(n):
    return f"{int(round(n)):,}".replace(",", " ") + " so'm"


def km_between(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def sizes_of(it):
    return json.loads(it["sizes"]) if it["sizes"] else None


def is_admin(tg):
    return tg == ADMIN_ID or bool(one("SELECT 1 FROM staff WHERE tg_id=? AND role='admin'", (tg,)))


def staff_ids(role, chef_type=None):
    if role == "admin":
        ids = {ADMIN_ID} | {r["tg_id"] for r in q("SELECT tg_id FROM staff WHERE role='admin'")}
        return list(ids)
    if chef_type:
        return [r["tg_id"] for r in q("SELECT tg_id FROM staff WHERE role='chef' AND chef_type=?", (chef_type,))]
    return [r["tg_id"] for r in q("SELECT tg_id FROM staff WHERE role=?", (role,))]


def role_of(tg):
    if is_admin(tg):
        return "admin"
    r = one("SELECT role FROM staff WHERE tg_id=?", (tg,))
    return r["role"] if r else "client"


def init():
    con.executescript("""
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS users(tg_id INTEGER PRIMARY KEY, name TEXT, surname TEXT, phone TEXT, photo TEXT, ref_by INTEGER, created INTEGER);
    CREATE TABLE IF NOT EXISTS staff(tg_id INTEGER, role TEXT, chef_type TEXT, name TEXT, phone TEXT, PRIMARY KEY(tg_id, role));
    CREATE TABLE IF NOT EXISTS menu(id INTEGER PRIMARY KEY AUTOINCREMENT, cat TEXT, sub TEXT, name TEXT, price INTEGER, unit TEXT, photo TEXT, sizes TEXT, stop INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, place_kind TEXT, place_no INTEGER, km REAL, addr TEXT, lat REAL, lon REAL,
        tg_id INTEGER, by_name TEXT, waiter_id INTEGER, status TEXT, sub INTEGER, fee INTEGER, disc INTEGER, total INTEGER, pay TEXT, courier_id INTEGER,
        live_msg INTEGER, ts INTEGER, closed INTEGER DEFAULT 0, paid_note TEXT);
    CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, name TEXT, size TEXT, price INTEGER, qty INTEGER, chef TEXT, ready INTEGER DEFAULT 0, extra INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, tg_id INTEGER, stars INTEGER, text TEXT, kind TEXT, ts INTEGER);
    CREATE TABLE IF NOT EXISTS referrals(inviter INTEGER, invited INTEGER PRIMARY KEY, bought INTEGER DEFAULT 0);
    """)
    con.commit()
    if not one("SELECT 1 FROM menu"):
        seed()


def seed():
    def add(cat, sub, name, price, unit="", sizes=None):
        ex("INSERT INTO menu(cat,sub,name,price,unit,sizes) VALUES(?,?,?,?,?,?)",
           (cat, sub, name, price, unit, json.dumps(sizes) if sizes else None))

    for n, p in [("Qovrilgan baliq", 100000), ("Tandirda pishgan baliq", 110000), ("Baliq shashlik", 120000), ("Losos steyk", 180000)]:
        add("food", "Baliq taomlari", n, p, "1 kg")
    add("food", "Oshlar", "Osh", 50000, "1 kg")
    for n, p in [("Choyxona oshi", 35000), ("Bayramlik osh", 40000), ("Devzira oshi", 45000)]:
        add("food", "Oshlar", n, p, "1 porsiya")
    for n, p in [("Mastava", 28000), ("Lag'mon", 32000), ("Sho'rva", 35000), ("Moshxo'rda", 25000), ("Chuchvara", 30000)]:
        add("food", "Suyuq ovqatlar", n, p, "1 porsiya")
    add("food", "Kabob va grill", "Mol go'shti shashlik", 18000, "1 six")
    add("food", "Kabob va grill", "Lyulya kabob", 16000, "1 six")

    def sz(b):
        r = lambda x: round(x / 500) * 500
        return {"0.5 l": b, "1 l": r(b * 1.6), "1.5 l": r(b * 2.2), "2 l": r(b * 2.7)}

    for n, b, sub in [("Coca-Cola", 6000, "Gazli ichimliklar"), ("Pepsi", 6000, "Gazli ichimliklar"), ("Fanta", 6000, "Gazli ichimliklar"),
                      ("Sprite", 6000, "Gazli ichimliklar"), ("Mirinda", 6000, "Gazli ichimliklar"), ("7UP", 6000, "Gazli ichimliklar"),
                      ("Dinay", 5000, "Suv va sharbat"), ("Bonaqua", 4000, "Suv va sharbat"), ("Rich sharbat", 9000, "Suv va sharbat"),
                      ("Lipton Ice Tea", 7000, "Suv va sharbat")]:
        add("drink", sub, n, b, "", sz(b))
    for n, p, u in [("Qora choy (choynak)", 8000, "1 choynak"), ("Ko'k choy (choynak)", 8000, "1 choynak"),
                    ("Qora choy (katta qota)", 14000, "1 qota"), ("Ko'k choy (katta qota)", 14000, "1 qota")]:
        add("drink", "Choy", n, p, u)
    for n, p in [("Achichuk", 15000), ("Toshkent salati", 28000), ("Cho'pon salati", 22000), ("Vitaminli salat", 18000),
                 ("Bodring-pomidor", 16000), ("Olivye", 25000), ("Sezar", 38000), ("Yunon salati", 30000),
                 ("Mimoza", 27000), ("Seld 'shuba'", 28000), ("Krab salati", 30000)]:
        add("salad", "Salatlar", n, p, "1 porsiya")


def place_label(o):
    if o["type"] == "delivery":
        return f"Dastavka ({o['km']:.1f} km)" if o["km"] else "Dastavka"
    return f"Ayvon, {o['place_no']}-stol" if o["place_kind"] == "ayvon" else f"Alohida xona, {o['place_no']}-xona"


def receipt(oid, title=""):
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    items = q("SELECT * FROM order_items WHERE order_id=?", (oid,))
    t = time.strftime("%d.%m.%Y %H:%M", time.localtime(o["ts"]))
    lines = ["🧾 <b>DASTURXON RESTORANI</b>", f"{title}№{oid} · {t}", f"📍 {place_label(o)}", "—" * 14]
    for i in items:
        sz = f" ({i['size']})" if i["size"] else ""
        lines.append(f"{i['name']}{sz}{' *' if i['extra'] else ''}\n   {i['qty']} x {som(i['price'])} = <b>{som(i['qty'] * i['price'])}</b>")
    lines.append("—" * 14)
    lines.append(f"Taomlar: {som(o['sub'])}")
    if o["fee"]:
        lines.append(f"Kuryer: {som(o['fee'])}")
    if o["disc"]:
        lines.append(f"Keshbek: -{som(o['disc'])}")
    lines.append(f"<b>UMUMIY: {som(o['total'])}</b>")
    return "\n".join(lines)


def cashback_on(tg):
    inv = one("SELECT COUNT(*) c, COALESCE(SUM(bought),0) b FROM referrals WHERE inviter=?", (tg,))
    return inv["c"] >= geti("ref_invite") and inv["b"] >= geti("ref_buyers")
