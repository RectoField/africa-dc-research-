"""
africa_dc_scraper.py
--------------------
A research tool for collecting and structuring publicly available data on
data center infrastructure across key African markets.

Produces a structured CSV dataset tracking facility locations, stated energy
sources, proximity to residential areas, and transparency gaps — intended
for use in environmental justice research and public-facing dashboards.

Research context: Data center expansion across Africa is accelerating, yet
most environmental impact data is either undisclosed or reported only in
aggregate by parent companies at a global level. This script treats data
absence as a finding, not a void.

Author: Lawson Emmanuel Runo
License: MIT
"""

import csv
import json
import time
import logging
import requests
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

COUNTRIES = {
    "Nigeria":      {"code": "NG", "bbox": "4.27,2.67,13.89,14.68"},
    "Kenya":        {"code": "KE", "bbox": "-4.68,33.91,4.62,41.90"},
    "Egypt":        {"code": "EG", "bbox": "22.00,24.70,31.67,36.90"},
    "South Africa": {"code": "ZA", "bbox": "-34.84,16.45,-22.13,32.89"},
}

# Known facilities compiled from public sources:
# corporate sustainability reports, regulatory filings, local press archives.
# Gaps are flagged explicitly — opacity is a finding, not a void.
KNOWN_FACILITIES = [
    {
        "name": "MDXi Lekki Data Centre",
        "operator": "MainOne / Meta",
        "country": "Nigeria",
        "city": "Lagos",
        "lat": 6.4355,
        "lon": 3.4412,
        "year_online": 2016,
        "energy_source": "Diesel + grid",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 2.1,
        "land_area_ha": None,
        "transparency_score": 1,
        "data_gap_note": (
            "No energy consumption figures published. Disclosures reduced "
            "following Meta acquisition. European facilities report PUE; "
            "Lagos facility does not."
        ),
        "sources": "OpenStreetMap; MainOne press releases; Meta sustainability report 2023",
    },
    {
        "name": "Medallion Data Centre Abuja",
        "operator": "Medallion Communications",
        "country": "Nigeria",
        "city": "Abuja",
        "lat": 9.0579,
        "lon": 7.4951,
        "year_online": 2010,
        "energy_source": "Diesel + grid",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 5.0,
        "land_area_ha": None,
        "transparency_score": 1,
        "data_gap_note": "No PUE, energy, or water data available in any public filing.",
        "sources": "Datacenter Hawk; company website",
    },
    {
        "name": "Galaxy Backbone National DC",
        "operator": "Galaxy Backbone (Federal Government)",
        "country": "Nigeria",
        "city": "Abuja",
        "lat": 9.0820,
        "lon": 7.4820,
        "year_online": 2009,
        "energy_source": "Unknown",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": None,
        "land_area_ha": None,
        "transparency_score": 1,
        "data_gap_note": (
            "Government-classified facility. No disclosures of any kind "
            "in public record. Existence confirmed via NCC regulatory filings."
        ),
        "sources": "NCC regulatory filings; Nigerian Tribune 2021",
    },
    {
        "name": "Telecom Egypt Data Centre (Cairo)",
        "operator": "Telecom Egypt (State)",
        "country": "Egypt",
        "city": "Cairo",
        "lat": 30.0444,
        "lon": 31.2357,
        "year_online": 2010,
        "energy_source": "Natural gas grid",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 0.5,
        "land_area_ha": None,
        "transparency_score": 1,
        "data_gap_note": (
            "State-owned operator. Annual reports exist but contain no "
            "facility-level energy, PUE, or water data."
        ),
        "sources": "Telecom Egypt annual report 2023; OpenStreetMap",
    },
    {
        "name": "Orange Business Services DC (Giza)",
        "operator": "Orange Business Services",
        "country": "Egypt",
        "city": "Giza",
        "lat": 30.0131,
        "lon": 31.2089,
        "year_online": 2017,
        "energy_source": "Natural gas grid",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 12.0,
        "land_area_ha": None,
        "transparency_score": 2,
        "data_gap_note": (
            "Orange regional ESG report covers MENA broadly. "
            "Cairo/Giza facility-level data excluded."
        ),
        "sources": "Orange Business ESG report 2023; Datacenter Hawk",
    },
    {
        "name": "KIXP Nairobi (Kenya IXP)",
        "operator": "TESPOK (non-profit)",
        "country": "Kenya",
        "city": "Nairobi",
        "lat": -1.2921,
        "lon": 36.8219,
        "year_online": 2000,
        "energy_source": "Kenya Power grid (~90% geothermal)",
        "energy_disclosed": True,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 0.3,
        "land_area_ha": None,
        "transparency_score": 3,
        "data_gap_note": None,
        "sources": "TESPOK public documentation; Kenya Power annual report 2023",
    },
    {
        "name": "Liquid Intelligent Technologies DC",
        "operator": "Liquid Intelligent Technologies",
        "country": "Kenya",
        "city": "Nairobi",
        "lat": -1.3190,
        "lon": 36.8880,
        "year_online": 2018,
        "energy_source": "Grid (geothermal-heavy) + diesel backup",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 3.2,
        "land_area_ha": None,
        "transparency_score": 2,
        "data_gap_note": (
            "Corporate sustainability reports are continent-level aggregates. "
            "No facility-specific figures for this site."
        ),
        "sources": "Liquid Intelligent 2023 report; Datacenter Hawk",
    },
    {
        "name": "Teraco JHB1 (Isando)",
        "operator": "Teraco Data Environments",
        "country": "South Africa",
        "city": "Johannesburg",
        "lat": -26.1596,
        "lon": 28.2231,
        "year_online": 2010,
        "energy_source": "Eskom grid (~80% coal) + partial solar PPA",
        "energy_disclosed": True,
        "pue_disclosed": True,
        "water_disclosed": False,
        "community_proximity_km": 6.0,
        "land_area_ha": 4.2,
        "transparency_score": 3,
        "data_gap_note": "Water consumption figures not disclosed.",
        "sources": "Teraco sustainability report 2023; OpenStreetMap",
    },
    {
        "name": "Africa Data Centres Johannesburg",
        "operator": "Africa Data Centres (Cassava Technologies)",
        "country": "South Africa",
        "city": "Johannesburg",
        "lat": -26.1050,
        "lon": 28.0560,
        "year_online": 2021,
        "energy_source": "Eskom grid + partial solar",
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": 8.0,
        "land_area_ha": None,
        "transparency_score": 2,
        "data_gap_note": (
            "Parent company Cassava reports at a pan-African level. "
            "No facility-specific ESG data published for this site."
        ),
        "sources": "Cassava Technologies ESG report 2023; Datacenter Hawk",
    },
    {
        "name": "NTT Cape Town",
        "operator": "NTT Ltd.",
        "country": "South Africa",
        "city": "Cape Town",
        "lat": -33.9249,
        "lon": 18.4241,
        "year_online": 2022,
        "energy_source": "Eskom + renewable PPAs",
        "energy_disclosed": True,
        "pue_disclosed": True,
        "water_disclosed": False,
        "community_proximity_km": 10.0,
        "land_area_ha": 2.1,
        "transparency_score": 3,
        "data_gap_note": "Water data absent despite NTT global reporting template including it.",
        "sources": "NTT sustainability report 2023; Cape Town City planning records",
    },
]


def fetch_osm_facilities(country: str, bbox: str) -> list[dict]:
    """
    Query OpenStreetMap Overpass API for data center nodes and ways
    within a given country bounding box.
    Returns raw OSM elements as a list of dicts.
    """
    query = f"""
    [out:json][timeout:30];
    (
      node["building"="data_center"]({bbox});
      way["building"="data_center"]({bbox});
      node["telecom"="data_center"]({bbox});
    );
    out center;
    """
    log.info(f"Querying OSM for data centers in {country}...")
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=35)
        r.raise_for_status()
        elements = r.json().get("elements", [])
        log.info(f"  → {len(elements)} OSM element(s) found in {country}")
        return elements
    except requests.RequestException as e:
        log.warning(f"  OSM query failed for {country}: {e}")
        return []


def osm_to_record(el: dict, country: str) -> dict:
    """Convert a raw OSM element into a flat research record."""
    tags = el.get("tags", {})
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    return {
        "name": tags.get("name", "Unnamed facility"),
        "operator": tags.get("operator", "Unknown"),
        "country": country,
        "city": tags.get("addr:city", ""),
        "lat": lat,
        "lon": lon,
        "year_online": None,
        "energy_source": tags.get("generator:source", "Unknown"),
        "energy_disclosed": False,
        "pue_disclosed": False,
        "water_disclosed": False,
        "community_proximity_km": None,
        "land_area_ha": None,
        "transparency_score": 1,
        "data_gap_note": "OSM-sourced entry. No corporate disclosures located.",
        "sources": f"OpenStreetMap (node/way id: {el.get('id')})",
    }


def compute_summary(records: list[dict]) -> dict:
    """
    Generate a summary statistics block for the dataset.
    Treats missing disclosures as explicit findings.
    """
    total = len(records)
    no_energy = sum(1 for r in records if not r["energy_disclosed"])
    no_pue    = sum(1 for r in records if not r["pue_disclosed"])
    no_water  = sum(1 for r in records if not r["water_disclosed"])
    avg_t     = round(sum(r["transparency_score"] for r in records) / total, 2) if total else 0
    by_country = {}
    for r in records:
        c = r["country"]
        by_country[c] = by_country.get(c, 0) + 1
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_facilities": total,
        "countries_covered": list(by_country.keys()),
        "facilities_per_country": by_country,
        "avg_transparency_score": avg_t,
        "pct_no_energy_data":  round(no_energy / total * 100, 1) if total else 0,
        "pct_no_pue_data":     round(no_pue    / total * 100, 1) if total else 0,
        "pct_no_water_data":   round(no_water  / total * 100, 1) if total else 0,
        "note": (
            "Transparency scores: 1=no public data, 2=aggregate only, "
            "3=partial facility-level, 4=most metrics disclosed, 5=full disclosure. "
            "No facility in this dataset has reached a score above 3. "
            "Absence of data is itself a finding."
        ),
    }


def write_csv(records: list[dict], path: str) -> None:
    if not records:
        log.warning("No records to write.")
        return
    fieldnames = list(records[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    log.info(f"Dataset written → {path} ({len(records)} records)")


def write_json(data: dict | list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"JSON written → {path}")


def run(osm: bool = True, out_csv: str = "africa_datacenters.csv",
        out_json: str = "africa_datacenters.json",
        summary_json: str = "summary.json") -> None:
    """
    Main pipeline:
      1. Start from the curated known-facilities list
      2. Optionally extend with live OSM data
      3. Deduplicate by name + country
      4. Write CSV + JSON outputs + summary
    """
    records = list(KNOWN_FACILITIES)

    if osm:
        seen = {(r["name"], r["country"]) for r in records}
        for country, meta in COUNTRIES.items():
            elements = fetch_osm_facilities(country, meta["bbox"])
            for el in elements:
                rec = osm_to_record(el, country)
                key = (rec["name"], rec["country"])
                if key not in seen:
                    records.append(rec)
                    seen.add(key)
            time.sleep(1.5)

    write_csv(records, out_csv)
    write_json(records, out_json)

    summary = compute_summary(records)
    write_json(summary, summary_json)

    log.info("\n--- Summary ---")
    log.info(f"  Facilities: {summary['total_facilities']}")
    log.info(f"  Avg transparency: {summary['avg_transparency_score']} / 5")
    log.info(f"  No energy data: {summary['pct_no_energy_data']}%")
    log.info(f"  No PUE data:    {summary['pct_no_pue_data']}%")
    log.info(f"  No water data:  {summary['pct_no_water_data']}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Scrape and structure African data center infrastructure data."
    )
    parser.add_argument("--no-osm", action="store_true",
                        help="Skip live OSM query, use curated dataset only")
    parser.add_argument("--csv",  default="africa_datacenters.csv")
    parser.add_argument("--json", default="africa_datacenters.json")
    parser.add_argument("--summary", default="summary.json")
    args = parser.parse_args()

    run(osm=not args.no_osm, out_csv=args.csv,
        out_json=args.json, summary_json=args.summary)
