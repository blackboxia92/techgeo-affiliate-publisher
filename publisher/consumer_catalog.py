from __future__ import annotations

import json
from pathlib import Path

from .mass_catalog import MassReport, generate_mass_catalog


PRODUCTS = (
    # Audio
    ("Sony WH-1000X Series", "sony-wh-1000x-series", "audio", "https://www.sony.com/electronics/headband-headphones/t/headband-style", "Sony", "Sony WH-1000X wireless headphones", "Bluetooth and 3.5 mm audio", "Over-ear wireless headphones", "Compare codec support, multipoint behavior, comfort, battery serviceability, and app requirements.", "Travel and focused listening with active noise cancellation."),
    ("Bose QuietComfort Series", "bose-quietcomfort-series", "audio", "https://www.bose.com/c/headphones", "Bose", "Bose QuietComfort headphones", "Bluetooth and wired audio", "Over-ear wireless headphones", "Check device compatibility, controls, replaceable cushions, carrying case, and wired fallback.", "Listeners prioritizing comfort and simple noise control."),
    ("JBL Charge Series", "jbl-charge-series", "audio", "https://www.jbl.com/bluetooth-speakers/", "JBL", "JBL Charge Bluetooth speaker", "Bluetooth and USB charging", "Portable wireless speaker", "Verify ingress rating, charging role, stereo pairing compatibility, weight, and battery care guidance.", "Portable listening where durability and battery capacity matter."),
    ("Ultimate Ears BOOM Series", "ultimate-ears-boom-series", "audio", "https://www.ultimateears.com/en-us/wireless-speakers", "Ultimate Ears", "Ultimate Ears BOOM speaker", "Bluetooth wireless audio", "Portable cylindrical speaker", "Check supported pairing modes, ingress protection, app support, charging connector, and placement.", "Outdoor and room-to-room listening with a compact enclosure."),
    ("Apple AirPods Series", "apple-airpods-series", "audio", "https://www.apple.com/airpods/", "Apple", "Apple AirPods", "Bluetooth with Apple ecosystem features", "True-wireless earbuds", "Confirm host-device feature support, fit, charging case connector, battery lifecycle, and hearing-safety settings.", "Apple-device users valuing automatic pairing and ecosystem integration."),
    ("Samsung Galaxy Buds Series", "samsung-galaxy-buds-series", "audio", "https://www.samsung.com/global/galaxy/galaxy-buds/", "Samsung", "Samsung Galaxy Buds", "Bluetooth with Galaxy ecosystem features", "True-wireless earbuds", "Check codec support, device switching, fit options, charging compatibility, and app availability.", "Android and Galaxy users seeking compact everyday audio."),
    ("Sennheiser Momentum Wireless Series", "sennheiser-momentum-wireless-series", "audio", "https://www.sennheiser-hearing.com/en-US/headphones/", "Sennheiser", "Sennheiser Momentum Wireless", "Bluetooth and wired audio", "Premium wireless headphones", "Compare codec availability, source compatibility, controls, comfort, and replaceable wear parts.", "Listeners prioritizing sound tuning and flexible connectivity."),
    ("Anker Soundcore Liberty Series", "soundcore-liberty-series", "audio", "https://www.soundcore.com/collections/true-wireless-earbuds", "Soundcore", "Soundcore Liberty earbuds", "Bluetooth wireless audio", "True-wireless earbuds", "Verify codec support, app features, ear-tip fit, charging options, call behavior, and warranty coverage.", "Value-focused everyday listening and calls."),

    # Home appliances and cleaning
    ("Dyson Cordless Vacuum Series", "dyson-cordless-vacuum-series", "home_appliances", "https://www.dyson.com/vacuum-cleaners/cordless", "Dyson", "Dyson cordless vacuum", "Battery-powered suction system", "Cordless stick vacuum", "Compare floor heads, filtration maintenance, bin handling, battery replacement, storage, and weight.", "Frequent multi-surface cleaning without a power cord."),
    ("Shark Cordless Vacuum Series", "shark-cordless-vacuum-series", "home_appliances", "https://www.sharkclean.com/page/vacuums", "SharkNinja", "Shark cordless vacuum", "Battery-powered suction system", "Cordless stick vacuum", "Check brush-roll design, filter washing, battery availability, folding storage, included tools, and floor compatibility.", "Homes balancing flexible cleaning and accessory options."),
    ("iRobot Roomba Series", "irobot-roomba-series", "home_appliances", "https://www.irobot.com/en_US/roomba.html", "iRobot", "iRobot Roomba robot vacuum", "Wi-Fi connected autonomous cleaning", "Robot vacuum", "Verify navigation features, mapping privacy, consumable availability, threshold clearance, dock space, and app support.", "Scheduled floor maintenance with minimal daily handling."),
    ("Roborock Robot Vacuum Series", "roborock-robot-vacuum-series", "home_appliances", "https://global.roborock.com/pages/robot-vacuum-cleaner", "Roborock", "Roborock robot vacuum", "Wi-Fi connected vacuum and mop platform", "Robot vacuum", "Compare dock functions, mapping controls, mop maintenance, obstacle handling, consumables, and floor suitability.", "Automated vacuuming and optional mopping with detailed mapping."),
    ("Philips Airfryer Series", "philips-airfryer-series", "home_appliances", "https://www.usa.philips.com/c-m-ho/cooking/airfryer", "Philips", "Philips Airfryer", "Mains-powered convection heating", "Countertop air fryer", "Check usable basket volume, circuit requirements, cleaning access, control layout, exterior clearance, and replacement parts.", "Everyday convection cooking with a removable basket."),
    ("Ninja Air Fryer Series", "ninja-air-fryer-series", "home_appliances", "https://www.sharkninja.com/ninja-kitchen/air-fryers", "SharkNinja", "Ninja air fryer", "Mains-powered convection heating", "Countertop air fryer", "Compare chamber layout, usable capacity, cleaning effort, circuit load, countertop footprint, and included accessories.", "Households choosing between compact and multi-zone cooking."),
    ("Nespresso Original Coffee System", "nespresso-original-system", "home_appliances", "https://www.nespresso.com/us/en/original-coffee-machines", "Nespresso", "Nespresso Original coffee machine", "Capsule-based pressure brewing", "Countertop coffee machine", "Verify capsule system, water-tank access, descaling process, cup clearance, regional voltage, and recycling options.", "Short espresso-style drinks with a compact capsule system."),
    ("Keurig K-Cup Brewer Series", "keurig-k-cup-brewer-series", "home_appliances", "https://www.keurig.com/Coffee-Makers/c/coffeemakers", "Keurig", "Keurig K-Cup coffee maker", "Capsule-based hot beverage brewing", "Countertop coffee brewer", "Check pod compatibility, reservoir design, cleaning cycle, brew sizes, electrical requirements, and countertop clearance.", "Convenient single-serve coffee in K-Cup markets."),

    # Power banks and charging
    ("Anker PowerCore Series", "anker-powercore-series", "power_charging", "https://www.anker.com/collections/power-banks", "Anker", "Anker PowerCore power bank", "USB portable power", "Portable battery pack", "Compare usable capacity, USB Power Delivery profiles, ports, recharge time, airline limits, cable needs, and warranty.", "General-purpose phone and tablet charging away from outlets."),
    ("Belkin BoostCharge Power Bank Series", "belkin-boostcharge-power-bank-series", "power_charging", "https://www.belkin.com/products/power-banks/", "Belkin", "Belkin BoostCharge power bank", "USB and optional magnetic wireless charging", "Portable battery pack", "Verify wired output profiles, magnetic-device compatibility, pass-through behavior, stand design, capacity, and thermal guidance.", "Everyday portable charging with broad accessory support."),
    ("UGREEN Nexode Power Bank Series", "ugreen-nexode-power-bank-series", "power_charging", "https://www.ugreen.com/collections/power-bank", "UGREEN", "UGREEN Nexode power bank", "USB-C Power Delivery", "High-output portable battery", "Check per-port power allocation, laptop charging profiles, display behavior, recharge input, cable rating, and flight compliance.", "USB-C laptops and multiple-device travel kits."),
    ("Baseus Blade Power Bank Series", "baseus-blade-power-bank-series", "power_charging", "https://www.baseus.com/collections/power-bank", "Baseus", "Baseus Blade power bank", "USB-C Power Delivery", "Flat portable battery", "Compare port sharing, supported voltage profiles, display accuracy, cable specifications, enclosure size, and travel restrictions.", "Laptop bags where a flat form factor is useful."),
    ("Anker Nano Charger Series", "anker-nano-charger-series", "power_charging", "https://www.anker.com/collections/chargers", "Anker", "Anker Nano USB C charger", "USB-C Power Delivery mains charging", "Compact wall charger", "Verify regional plug, total and per-port output, host charging protocol, cable rating, thermal clearance, and warranty.", "Compact everyday charging for phones, tablets, and selected laptops."),
    ("Belkin GaN Wall Charger Series", "belkin-gan-wall-charger-series", "power_charging", "https://www.belkin.com/products/chargers/wall-chargers/", "Belkin", "Belkin GaN USB C charger", "USB-C Power Delivery mains charging", "Multi-port wall charger", "Check plug format, port allocation under load, device profiles, cable needs, safety certifications, and placement.", "Multi-device charging from a compact wall adapter."),
    ("UGREEN Nexode Charger Series", "ugreen-nexode-charger-series", "power_charging", "https://www.ugreen.com/collections/gan-charger", "UGREEN", "UGREEN Nexode GaN charger", "USB-C and USB-A mains charging", "Multi-port GaN wall charger", "Compare simultaneous-output tables, regional plug, cable requirements, supported protocols, heat management, and warranty.", "Desk and travel kits charging several device classes."),
    ("Apple MagSafe Charger", "apple-magsafe-charger", "power_charging", "https://www.apple.com/shop/product/MHXH3AM/A/magsafe-charger", "Apple", "Apple MagSafe Charger", "Magnetic Qi-family wireless charging", "Wireless charging puck", "Confirm device generation, power-adapter requirement, negotiated charging rate, case compatibility, cable length, and heat behavior.", "Compatible iPhone users wanting aligned wireless charging."),

    # Everyday gadgets
    ("Amazon Kindle E-reader Series", "amazon-kindle-series", "gadgets", "https://www.amazon.com/b?node=6669702011", "Amazon", "Amazon Kindle e-reader", "Wi-Fi e-reading platform", "Dedicated e-reader", "Compare display lighting, storage, file workflow, waterproofing, library compatibility, ecosystem lock-in, and case options.", "Long-form reading with a low-distraction display."),
    ("Kobo E-reader Series", "kobo-ereader-series", "gadgets", "https://www.kobo.com/ereaders", "Rakuten Kobo", "Kobo e-reader", "Wi-Fi e-reading platform", "Dedicated e-reader", "Check regional store and library support, file formats, display size, lighting, waterproofing, stylus compatibility, and storage.", "Readers valuing format flexibility and regional library integrations."),
    ("Apple Watch Series", "apple-watch-series", "gadgets", "https://www.apple.com/watch/", "Apple", "Apple Watch", "Bluetooth, Wi-Fi, and optional cellular wearable", "Smartwatch", "Verify iPhone requirements, case size, health-feature regional availability, band compatibility, charging, and cellular plan support.", "iPhone users seeking integrated notifications, fitness, and safety features."),
    ("Samsung Galaxy Watch Series", "samsung-galaxy-watch-series", "gadgets", "https://www.samsung.com/global/galaxy/galaxy-watch/", "Samsung", "Samsung Galaxy Watch", "Bluetooth, Wi-Fi, and optional cellular wearable", "Smartwatch", "Check Android compatibility, phone-vendor feature limits, size, health-feature availability, charging, bands, and carrier support.", "Android users wanting a full-featured smartwatch."),
    ("Tile Bluetooth Tracker Series", "tile-tracker-series", "gadgets", "https://www.tile.com/products", "Tile", "Tile Bluetooth tracker", "Bluetooth crowdsourced finding network", "Item tracker", "Compare network coverage, phone support, replaceable battery options, subscription features, attachment method, and privacy controls.", "Cross-platform tracking for keys, bags, and household items."),
    ("Apple AirTag", "apple-airtag", "gadgets", "https://www.apple.com/airtag/", "Apple", "Apple AirTag", "Bluetooth and ultra-wideband finding network", "Item tracker", "Confirm Apple-device requirements, accessory needs, battery replacement, anti-stalking safeguards, precision-finding support, and intended use.", "Apple ecosystem users tracking compatible personal items."),
    ("Logitech MX Mouse Series", "logitech-mx-mouse-series", "gadgets", "https://www.logitech.com/en-us/mx/mx-for-business.html", "Logitech", "Logitech MX wireless mouse", "Bluetooth and USB receiver", "Wireless productivity mouse", "Check hand fit, operating-system features, receiver type, multi-device switching, software policy, charging, and button mapping.", "Desktop productivity across one or more computers."),
    ("Elgato Stream Deck Series", "elgato-stream-deck-series", "gadgets", "https://www.elgato.com/us/en/s/welcome-to-stream-deck", "Elgato", "Elgato Stream Deck", "USB programmable control surface", "Desktop macro controller", "Verify operating-system support, application plugins, USB connection, desk footprint, profile portability, and workflow maintenance.", "Repeatable shortcuts for creators, meetings, and desktop automation."),
)


INTENTS = tuple(
    (name, slug)
    for name, slug in (
        ("small apartments with limited storage", "small-apartments-limited-storage"),
        ("busy households prioritizing simple maintenance", "busy-households-simple-maintenance"),
        ("shared homes needing intuitive controls", "shared-homes-intuitive-controls"),
        ("frequent travelers minimizing bag weight", "frequent-travelers-low-weight"),
        ("remote workers building a reliable daily setup", "remote-workers-reliable-setup"),
        ("students balancing durability and total cost", "students-durability-total-cost"),
        ("gift buyers avoiding ecosystem surprises", "gift-buyers-compatibility"),
        ("families prioritizing replaceable consumables", "families-replaceable-consumables"),
        ("buyers planning three years of regular use", "three-year-regular-use"),
        ("first-time buyers wanting a low learning curve", "first-time-buyers-low-learning-curve"),
        ("multi-device homes standardizing accessories", "multi-device-homes-standardizing"),
        ("daily commuters needing compact equipment", "daily-commuters-compact-equipment"),
        ("users prioritizing repair and replacement options", "repair-replacement-options"),
        ("buyers comparing operating effort over headline features", "operating-effort-over-features"),
        ("homes with mixed flooring and room layouts", "mixed-flooring-room-layouts"),
        ("listeners switching between calls and entertainment", "calls-and-entertainment"),
        ("travel kits serving phones tablets and laptops", "travel-multi-device-kits"),
        ("households reducing cable and charger clutter", "reduce-charger-clutter"),
        ("buyers prioritizing privacy and offline operation", "privacy-offline-operation"),
        ("users needing accessible everyday controls", "accessible-everyday-controls"),
        ("compact kitchens with limited counter space", "compact-kitchens-counter-space"),
        ("pet households managing routine floor cleaning", "pet-households-floor-cleaning"),
        ("buyers comparing warranty and support paths", "warranty-support-paths"),
        ("users prioritizing battery longevity", "battery-longevity"),
        ("households balancing performance and noise", "performance-and-noise"),
        ("buyers avoiding unnecessary subscriptions", "avoid-subscriptions"),
        ("everyday users seeking predictable ownership costs", "predictable-ownership-costs"),
    )
)


def generate_consumer_catalog(*, pages_root: Path, catalog_path: Path, source_path: Path, total: int = 4000) -> MassReport:
    products = []
    for name, slug, category, url, publisher, query, interface, form, operations, best_for in PRODUCTS:
        products.append(
            {
                "name": name,
                "slug": slug,
                "category": category,
                "official_url": url,
                "publisher": publisher,
                "amazon_query": query,
                "summary": f"An established {form.lower()} family evaluated through stable compatibility and ownership criteria.",
                "interface": interface,
                "form": form,
                "operations": operations,
                "best_for": best_for,
                "decision": best_for.rstrip(".").lower(),
                "memory_channel": "N/A — consumer appliance or peripheral without user-addressable system RAM",
                "ram_limit": "N/A — consumer appliance or peripheral without user-addressable system RAM",
                "idle_watts": "Not stated here — power varies by exact model and operating mode; consult the linked manufacturer documentation",
            }
        )
    payload = {
        "version": 1,
        "content_policy": "Evergreen comparisons omit live prices, stock, ratings, and model-year claims.",
        "products": products,
        "intents": [{"name": name, "slug": slug} for name, slug in INTENTS],
    }
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return generate_mass_catalog(
        source_path=source_path,
        pages_root=pages_root,
        catalog_path=catalog_path,
        total=total,
        origin="consumer-products-v1",
        output_subdir="consumer",
    )
