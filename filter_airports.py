import csv, json, os

src = os.path.join(os.path.dirname(__file__), "airports.csv")
out = os.path.join(os.path.dirname(__file__), "app", "static", "js", "airports.json")

airports = []
with open(src, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        iata = row.get("iata_code", "").strip()
        kind = row.get("type", "").strip()
        if not iata or kind == "closed" or kind == "heliport" or kind == "balloonport" or kind == "seaplane_base":
            continue
        name = row.get("name", "").strip()
        city = row.get("municipality", "").strip()
        country = row.get("iso_country", "").strip()
        airports.append({"iata": iata, "name": name, "city": city, "country": country})

airports.sort(key=lambda x: x["iata"])

with open(out, "w", encoding="utf-8") as f:
    json.dump(airports, f, separators=(",", ":"))

print(f"Done — {len(airports)} airports saved to {out}")
