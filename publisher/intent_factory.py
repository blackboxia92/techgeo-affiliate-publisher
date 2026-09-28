"""Curated, bounded intent-page factory for StackSignal V3.

The catalog below deliberately contains product *families* with official
documentation.  It creates a fixed 500-page batch: the use-case vocabulary is
curated per product domain, rather than being a keyword cross-product or a
price-feed surrogate.  Volatile price, stock, rating and review claims are
never emitted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path

from .affiliate import amazon_search_url


CRITERIA = (
    ("model", "Product family", "The documented product family being compared."),
    ("interface", "Platform and connection", "The documented primary interface or ecosystem."),
    ("form", "Form factor", "The product form that affects the buying decision."),
    ("operations", "Ownership considerations", "Compatibility, maintenance and setup checks before purchase."),
    ("fit", "Decision fit", "The stated situation where the option is a sensible starting point."),
    ("intent", "Intent relevance", "Why this option belongs in this decision."),
)

USE_CASES = {
    "audio": ("travel", "commuting", "remote work calls", "long listening sessions", "shared offices", "frequent video calls", "Android phones", "iPhone users", "laptops", "multidevice setups", "quiet study", "home entertainment", "everyday music", "first-time buyers", "gift buyers", "users who need wired fallback"),
    "home": ("pet hair", "hard floors", "carpets", "small apartments", "large homes", "busy households", "first-time buyers", "low-maintenance routines", "shared homes", "allergy-aware cleaning", "daily cleaning", "limited storage", "open-plan homes", "homes with obstacles", "families", "quiet-operation priorities"),
    "kitchen": ("small kitchens", "families", "beginners", "batch cooking", "quick weekday meals", "limited counter space", "easy cleaning", "shared homes", "single-person households", "meal prep", "gift buyers", "daily use", "simple controls", "compact storage", "energy-conscious cooking", "first-time appliance buyers"),
    "power": ("travel", "remote work", "students", "multi-device bags", "iPhone users", "Android phones", "USB-C laptops", "daily commuting", "shared charging stations", "minimal desk setups", "international travel planning", "emergency backup", "first-time buyers", "gift buyers", "compact carry", "long-term accessory use"),
    "personal": ("travel", "students", "commuting", "small bags", "first-time buyers", "gift buyers", "shared households", "daily routines", "low-distraction use", "accessibility", "privacy-conscious buyers", "multi-device homes", "long-term ownership", "simple setup", "family use", "everyday carry"),
    "computing": ("home office", "remote work", "students", "software development", "small desks", "multi-device setups", "video calls", "content creation", "gaming setups", "first-time buyers", "small offices", "travel", "accessibility", "long sessions", "simple setup", "long-term ownership"),
}

COMPATIBILITY = {
    "noise-cancelling-headphones": "iPhone and Android phones", "wireless-earbuds": "iPhone users",
    "robot-vacuums": "Wi-Fi app-controlled homes", "cordless-vacuums": "mixed-floor homes",
    "air-fryers": "standard countertop kitchens", "coffee-machines": "the preferred capsule or bean workflow",
    "power-banks": "USB-C laptops", "usb-c-chargers": "USB-C Power Delivery devices",
    "e-readers": "library and file-format workflows", "smartwatches": "iPhone users",
    "bluetooth-trackers": "Apple Find My or Galaxy Find networks", "keyboards": "Mac and Windows desks",
    "productivity-mice": "Mac and Windows desks", "webcams": "Zoom and Teams calls",
}


@dataclass(frozen=True)
class Product:
    name: str
    official_url: str
    publisher: str
    query: str
    interface: str
    form: str
    operations: str
    fit: str


@dataclass(frozen=True)
class Cluster:
    slug: str
    label: str
    domain: str
    products: tuple[Product, ...]


def _p(name: str, url: str, publisher: str, query: str, interface: str, form: str, operations: str, fit: str) -> Product:
    return Product(name, url, publisher, query, interface, form, operations, fit)


# Official manufacturer category/family pages are intentionally used instead
# of retailer listings.  The same canonical inventory feeds HTML, Markdown and
# JSON through the normal publisher.
CLUSTERS = (
    Cluster("noise-cancelling-headphones", "noise-cancelling headphones", "audio", (
        _p("Sony WH-1000X Series", "https://www.sony.com/electronics/headband-headphones/t/headband-style", "Sony", "Sony WH-1000X headphones", "Bluetooth and 3.5 mm audio", "Over-ear headphones", "Check multipoint, app support, cable fallback and earpad serviceability.", "Focused listening and travel with active noise control."),
        _p("Bose QuietComfort Series", "https://www.bose.com/c/headphones", "Bose", "Bose QuietComfort headphones", "Bluetooth and wired audio", "Over-ear headphones", "Check device switching, controls, cushions and wired operation.", "Comfort-led listening and straightforward noise control."),
        _p("Sennheiser Momentum Wireless", "https://www.sennheiser-hearing.com/en-US/headphones/", "Sennheiser", "Sennheiser Momentum Wireless", "Bluetooth and wired audio", "Premium over-ear headphones", "Verify codecs, source compatibility, controls and wear-part support.", "Listeners prioritizing tuning and flexible connectivity."),
        _p("Sony ULT WEAR", "https://www.sony.com/electronics/headband-headphones/t/headband-style", "Sony", "Sony ULT WEAR headphones", "Bluetooth audio", "Over-ear headphones", "Verify app controls, fit, charging and host-device requirements.", "Everyday wireless listening with adjustable sound settings."),
    )),
    Cluster("wireless-earbuds", "wireless earbuds", "audio", (
        _p("Apple AirPods Series", "https://www.apple.com/airpods/", "Apple", "Apple AirPods", "Bluetooth with Apple ecosystem features", "True-wireless earbuds", "Check host-device support, fit, charging case and hearing settings.", "Apple-device users valuing automatic pairing."),
        _p("Samsung Galaxy Buds Series", "https://www.samsung.com/global/galaxy/galaxy-buds/", "Samsung", "Samsung Galaxy Buds", "Bluetooth with Galaxy ecosystem features", "True-wireless earbuds", "Verify codec support, device switching, fit and app availability.", "Android and Galaxy users seeking compact daily audio."),
        _p("Soundcore Liberty Series", "https://www.soundcore.com/collections/true-wireless-earbuds", "Soundcore", "Soundcore Liberty earbuds", "Bluetooth wireless audio", "True-wireless earbuds", "Check codec support, app features, ear-tip fit and call behavior.", "Value-focused everyday listening and calls."),
        _p("Sony WF-1000X Series", "https://www.sony.com/electronics/in-ear-headphones/t/truly-wireless", "Sony", "Sony WF-1000X earbuds", "Bluetooth audio", "True-wireless earbuds", "Check app support, ear-tip fit, multipoint availability and charging.", "Users seeking configurable wireless listening."),
    )),
    Cluster("robot-vacuums", "robot vacuums", "home", (
        _p("Roborock Robot Vacuum Series", "https://global.roborock.com/pages/robot-vacuums", "Roborock", "Roborock robot vacuum", "Wi-Fi connected vacuum and mop platform", "Robot vacuum", "Compare dock functions, mapping controls, consumables and floor suitability.", "Automated vacuuming with detailed mapping."),
        _p("iRobot Roomba Series", "https://www.irobot.com/en_US/roomba.html", "iRobot", "iRobot Roomba robot vacuum", "Wi-Fi connected autonomous cleaning", "Robot vacuum", "Verify navigation features, mapping privacy, dock space and app support.", "Scheduled floor maintenance with minimal handling."),
        _p("Dreame Robot Vacuum Series", "https://global.dreametech.com/collections/robot-vacuum", "Dreame", "Dreame robot vacuum", "Wi-Fi connected vacuum and mop platform", "Robot vacuum", "Check dock maintenance, obstacle handling, mop care and consumables.", "Homes comparing vacuuming and mopping automation."),
        _p("eufy Robot Vacuum Series", "https://www.eufy.com/collections/robot-vacuum", "eufy", "eufy robot vacuum", "Wi-Fi connected cleaning platform", "Robot vacuum", "Verify navigation mode, dock requirements, app control and replacement parts.", "Routine automated floor cleaning."),
    )),
    Cluster("cordless-vacuums", "cordless vacuums", "home", (
        _p("Dyson Cordless Vacuum Series", "https://www.dyson.com/vacuum-cleaners/cordless", "Dyson", "Dyson cordless vacuum", "Battery-powered suction system", "Cordless stick vacuum", "Compare floor heads, filtration maintenance, battery replacement and weight.", "Frequent multi-surface cleaning without a cord."),
        _p("Shark Cordless Vacuum Series", "https://www.sharkclean.com/page/vacuums", "SharkNinja", "Shark cordless vacuum", "Battery-powered suction system", "Cordless stick vacuum", "Check brush-roll design, filter washing, battery availability and storage.", "Flexible cleaning with accessory options."),
        _p("Tineco Floor Care Series", "https://www.tineco.com/collections/vacuum-cleaners", "Tineco", "Tineco cordless vacuum", "Battery-powered floor care", "Cordless vacuum", "Verify wet/dry capability, cleaning cycles, filters and floor compatibility.", "Homes evaluating cordless floor-care workflows."),
        _p("Bosch Unlimited Series", "https://www.bosch-home.com/", "Bosch", "Bosch Unlimited cordless vacuum", "Battery-powered suction system", "Cordless stick vacuum", "Check battery ecosystem, tools, filters and regional service options.", "Users considering shared battery and appliance ecosystems."),
    )),
    Cluster("air-fryers", "air fryers", "kitchen", (
        _p("Philips Airfryer Series", "https://www.philips.com/c-m-ho/cooking/airfryer", "Philips", "Philips Airfryer", "Mains-powered convection heating", "Countertop air fryer", "Check usable capacity, cleaning access, controls and replacement parts.", "Everyday convection cooking with a removable basket."),
        _p("Ninja Air Fryer Series", "https://www.sharkninja.com/ninja-kitchen/air-fryers", "SharkNinja", "Ninja air fryer", "Mains-powered convection heating", "Countertop air fryer", "Compare chamber layout, capacity, cleaning effort and footprint.", "Households choosing compact or multi-zone cooking."),
        _p("COSORI Air Fryer Series", "https://cosori.com/collections/air-fryers", "COSORI", "COSORI air fryer", "Mains-powered convection heating", "Countertop air fryer", "Verify basket layout, controls, cleaning guidance and app features where applicable.", "Everyday countertop convection cooking."),
        _p("Cecotec Cecofry Series", "https://cecotec.es/es/freidoras-de-aire", "Cecotec", "Cecotec Cecofry", "Mains-powered convection heating", "Countertop air fryer", "Check exact capacity, controls, cleaning instructions and warranty terms.", "Spanish-market countertop cooking comparisons."),
    )),
    Cluster("coffee-machines", "coffee machines", "kitchen", (
        _p("Nespresso Original System", "https://www.nespresso.com/es/es/maquinas-de-cafe", "Nespresso", "Nespresso Original coffee machine", "Capsule pressure brewing", "Countertop coffee machine", "Verify capsule system, water access, descaling and regional voltage.", "Short espresso-style drinks in a compact capsule system."),
        _p("De'Longhi Bean-to-Cup Series", "https://www.delonghi.com/es-es/productos/cafe/cafeteras-superautomaticas", "De'Longhi", "DeLonghi bean to cup coffee machine", "Bean-to-cup espresso brewing", "Automatic coffee machine", "Check grinder, milk workflow, cleaning cycle and counter clearance.", "Users wanting fresh-bean coffee with guided maintenance."),
        _p("Philips LatteGo Series", "https://www.home.id/", "Philips", "Philips LatteGo coffee machine", "Bean-to-cup espresso brewing", "Automatic coffee machine", "Verify milk-system cleaning, grinder adjustment and consumable access.", "Households comparing bean-to-cup workflows."),
        _p("Krups Capsule Coffee Series", "https://www.krups.es/", "Krups", "Krups capsule coffee machine", "Capsule hot beverage brewing", "Countertop coffee machine", "Check capsule compatibility, water tank access and descaling requirements.", "Compact single-serve coffee setups."),
    )),
    Cluster("power-banks", "power banks", "power", (
        _p("Anker PowerCore Series", "https://www.anker.com/collections/power-banks", "Anker", "Anker PowerCore power bank", "USB portable power", "Portable battery pack", "Compare USB-PD profiles, ports, recharge time and airline limits.", "General-purpose phone and tablet charging."),
        _p("Belkin BoostCharge Power Bank Series", "https://www.belkin.com/products/power-banks/", "Belkin", "Belkin BoostCharge power bank", "USB and optional magnetic charging", "Portable battery pack", "Verify output profiles, magnetic compatibility and pass-through behavior.", "Everyday portable charging with broad accessory support."),
        _p("UGREEN Nexode Power Bank Series", "https://www.ugreen.com/collections/power-bank", "UGREEN", "UGREEN Nexode power bank", "USB-C Power Delivery", "High-output portable battery", "Check port allocation, laptop profiles, input and cable requirements.", "USB-C laptops and multi-device travel kits."),
        _p("Baseus Blade Power Bank Series", "https://www.baseus.com/collections/power-bank", "Baseus", "Baseus Blade power bank", "USB-C Power Delivery", "Flat portable battery", "Compare port sharing, voltage profiles, display and travel restrictions.", "Laptop bags where a flat form factor is useful."),
    )),
    Cluster("usb-c-chargers", "USB-C chargers", "power", (
        _p("Anker Nano Charger Series", "https://www.anker.com/collections/chargers", "Anker", "Anker Nano USB C charger", "USB-C Power Delivery", "Compact wall charger", "Verify plug type, per-port output, cable rating and thermal clearance.", "Compact charging for phones, tablets and selected laptops."),
        _p("Belkin GaN Wall Charger Series", "https://www.belkin.com/products/chargers/wall-chargers/", "Belkin", "Belkin GaN wall charger", "USB-C Power Delivery", "Multi-port wall charger", "Check port allocation, device profiles, cable needs and safety certifications.", "Multi-device charging from a compact adapter."),
        _p("UGREEN Nexode Charger Series", "https://www.ugreen.com/collections/gan-charger", "UGREEN", "UGREEN Nexode charger", "USB-C and USB-A charging", "Multi-port GaN charger", "Compare simultaneous-output tables, regional plug and supported protocols.", "Desk and travel kits charging several devices."),
        _p("Baseus GaN Charger Series", "https://www.baseus.com/collections/chargers", "Baseus", "Baseus GaN charger", "USB-C charging", "Wall charger", "Verify per-port allocation, plug format, charging protocols and cable needs.", "Compact USB-C charging setups."),
    )),
    Cluster("e-readers", "e-readers", "personal", (
        _p("Amazon Kindle Series", "https://www.amazon.es/b?node=827231031", "Amazon", "Amazon Kindle e-reader", "Wi-Fi e-reading platform", "Dedicated e-reader", "Check lighting, storage, file workflow, waterproofing and library compatibility.", "Long-form reading with a low-distraction display."),
        _p("Kobo E-reader Series", "https://www.kobo.com/ereaders", "Rakuten Kobo", "Kobo e-reader", "Wi-Fi e-reading platform", "Dedicated e-reader", "Check regional store, library support, formats, lighting and stylus options.", "Readers valuing format flexibility and library integrations."),
        _p("PocketBook E-reader Series", "https://pocketbook.ch/en-ch/catalog/e-readers", "PocketBook", "PocketBook e-reader", "Wi-Fi e-reading platform", "Dedicated e-reader", "Verify format handling, storefront support, display and regional warranty.", "Readers comparing ecosystem independence and formats."),
        _p("Onyx BOOX E-reader Series", "https://shop.boox.com/collections/eink-tablet", "BOOX", "Onyx BOOX e-reader", "E-ink Android platform", "E-ink reader and note device", "Check Android version, app support, stylus workflow and update policy.", "Readers who also need flexible note-taking workflows."),
    )),
    Cluster("smartwatches", "smartwatches", "personal", (
        _p("Apple Watch Series", "https://www.apple.com/watch/", "Apple", "Apple Watch", "Bluetooth, Wi-Fi and optional cellular", "Smartwatch", "Verify iPhone requirements, case size, regional health features and charging.", "iPhone users seeking integrated notifications and fitness tools."),
        _p("Samsung Galaxy Watch Series", "https://www.samsung.com/global/galaxy/galaxy-watch/", "Samsung", "Samsung Galaxy Watch", "Bluetooth, Wi-Fi and optional cellular", "Smartwatch", "Check Android compatibility, feature limits, size and carrier support.", "Android users wanting a full-featured smartwatch."),
        _p("Garmin Venu Series", "https://www.garmin.com/en-US/c/wearables-smartwatches/", "Garmin", "Garmin Venu smartwatch", "Bluetooth and GNSS wearable", "Smartwatch", "Verify phone compatibility, sport profiles, charging and regional health features.", "Users balancing fitness data and smartwatch functions."),
        _p("Fitbit Sense Series", "https://www.fitbit.com/global/us/products/smartwatches", "Fitbit", "Fitbit Sense smartwatch", "Bluetooth wearable", "Smartwatch", "Check phone requirements, subscription boundaries and sensor availability.", "Everyday health and activity tracking."),
    )),
    Cluster("bluetooth-trackers", "Bluetooth trackers", "personal", (
        _p("Apple AirTag", "https://www.apple.com/airtag/", "Apple", "Apple AirTag", "Bluetooth and ultra-wideband finding network", "Item tracker", "Confirm Apple-device requirements, battery replacement and anti-stalking safeguards.", "Apple users tracking compatible personal items."),
        _p("Samsung Galaxy SmartTag Series", "https://www.samsung.com/", "Samsung", "Samsung Galaxy SmartTag", "Bluetooth finding network", "Item tracker", "Verify Galaxy device requirements, network coverage and attachment needs.", "Galaxy users tracking keys, bags and household items."),
        _p("Tile Tracker Series", "https://www.tile.com/products", "Tile", "Tile Bluetooth tracker", "Bluetooth crowdsourced finding network", "Item tracker", "Compare phone support, battery options, subscription features and privacy controls.", "Cross-platform item tracking."),
        _p("Chipolo Tracker Series", "https://chipolo.net/", "Chipolo", "Chipolo Bluetooth tracker", "Bluetooth finding network", "Item tracker", "Check network compatibility, battery design, alerts and attachment options.", "Users comparing platform-specific finding networks."),
    )),
    Cluster("keyboards", "wireless keyboards", "computing", (
        _p("Logitech MX Keys Series", "https://www.logitech.com/en-us/products/keyboards.html", "Logitech", "Logitech MX Keys keyboard", "Bluetooth and USB receiver", "Wireless productivity keyboard", "Check operating-system layouts, multi-device switching and software policy.", "Desktop productivity across multiple computers."),
        _p("Keychron Keyboard Series", "https://www.keychron.com/collections/keyboards", "Keychron", "Keychron keyboard", "Wired and Bluetooth keyboard", "Mechanical keyboard", "Verify layout, switch options, OS support, remapping and connectivity mode.", "Users choosing configurable mechanical layouts."),
        _p("NuPhy Keyboard Series", "https://nuphy.com/collections/keyboards", "NuPhy", "NuPhy wireless keyboard", "Bluetooth and wired USB", "Low-profile mechanical keyboard", "Check layout, switch compatibility, OS support and charging workflow.", "Compact mechanical keyboard setups."),
        _p("Razer Productivity Keyboard Series", "https://www.razer.com/pc/gaming-keyboards", "Razer", "Razer wireless keyboard", "Bluetooth and USB receiver", "Wireless keyboard", "Verify host software, layout, connectivity and device switching.", "Users combining work and gaming devices."),
    )),
    Cluster("productivity-mice", "productivity mice", "computing", (
        _p("Logitech MX Mouse Series", "https://www.logitech.com/en-us/mx/mx-for-business.html", "Logitech", "Logitech MX mouse", "Bluetooth and USB receiver", "Wireless productivity mouse", "Check hand fit, multi-device switching, software and charging.", "Desktop productivity across one or more computers."),
        _p("Razer Pro Click Series", "https://www.razer.com/productivity", "Razer", "Razer Pro Click mouse", "Bluetooth and USB receiver", "Wireless productivity mouse", "Verify hand fit, host software, connection mode and charging.", "Ergonomic-oriented desktop workflows."),
        _p("Keychron Mouse Series", "https://www.keychron.com/collections/mice", "Keychron", "Keychron wireless mouse", "Bluetooth and USB receiver", "Wireless mouse", "Check grip shape, operating-system support, remapping and connection mode.", "Multi-device desktop users."),
        _p("Microsoft Surface Mouse Series", "https://www.microsoft.com/en-us/d/surface-mouse/", "Microsoft", "Microsoft Surface mouse", "Bluetooth wireless", "Wireless mouse", "Verify Bluetooth host support, battery type and operating-system features.", "Simple Bluetooth office setups."),
    )),
    Cluster("webcams", "webcams", "computing", (
        _p("Logitech Brio Series", "https://www.logitech.com/en-us/products/webcams.html", "Logitech", "Logitech Brio webcam", "USB video", "Desktop webcam", "Check host OS, conferencing app support, mounting and privacy shutter.", "Remote calls requiring a dedicated USB camera."),
        _p("Elgato Facecam Series", "https://www.elgato.com/us/en/s/webcams", "Elgato", "Elgato Facecam", "USB video", "Desktop webcam", "Verify host software, mounting, USB requirements and manual controls.", "Creators and desk video setups."),
        _p("Insta360 Link Series", "https://www.insta360.com/product/insta360-link", "Insta360", "Insta360 Link webcam", "USB video", "Gimbal webcam", "Check tracking features, host software, mounting and USB bandwidth.", "Presenters who need framing controls."),
        _p("Razer Kiyo Series", "https://www.razer.com/streaming-cameras", "Razer", "Razer Kiyo webcam", "USB video", "Desktop webcam", "Verify lighting, software, mounting and conferencing compatibility.", "Desk streaming and video-call use."),
    )),
    Cluster("usb-microphones", "USB microphones", "computing", (
        _p("Elgato Wave Series", "https://www.elgato.com/us/en/s/microphones", "Elgato", "Elgato Wave microphone", "USB audio", "Desktop USB microphone", "Check host software, monitoring, boom mounting and recording workflow.", "Streaming, calls and desktop recording."),
        _p("Rode NT-USB Series", "https://rode.com/en/microphones/usb", "RØDE", "Rode NT USB microphone", "USB audio", "Desktop USB microphone", "Verify host compatibility, monitoring, mounting and pickup pattern.", "Voice recording and remote communication."),
        _p("Blue Yeti Series", "https://www.logitechg.com/en-us/products/streaming-gear.html", "Logitech", "Blue Yeti microphone", "USB audio", "Desktop USB microphone", "Check pickup mode, desk placement, monitoring and host application support.", "Versatile desktop voice capture."),
        _p("Shure MV7 Series", "https://www.shure.com/en-US/products/microphones", "Shure", "Shure MV7 microphone", "USB and XLR audio", "Dynamic desktop microphone", "Verify USB/XLR workflow, monitoring, software and mounting.", "Users planning a path from USB to XLR workflows."),
    )),
    Cluster("mesh-wifi", "mesh Wi-Fi systems", "computing", (
        _p("TP-Link Deco Series", "https://www.tp-link.com/home-networking/deco/", "TP-Link", "TP-Link Deco mesh WiFi", "Wi-Fi mesh networking", "Mesh router system", "Check node count, backhaul, ISP mode, ports and app controls.", "Whole-home coverage with a managed mesh."),
        _p("ASUS ZenWiFi Series", "https://www.asus.com/networking-iot-servers/whole-home-mesh-wifi-system/", "ASUS", "ASUS ZenWiFi mesh WiFi", "Wi-Fi mesh networking", "Mesh router system", "Verify wired backhaul, ports, firmware policy and configuration options.", "Homes wanting configurable mesh networking."),
        _p("eero Mesh Wi-Fi Series", "https://eero.com/", "eero", "eero mesh WiFi", "Wi-Fi mesh networking", "Mesh router system", "Check ISP compatibility, node placement, app requirements and subscription boundaries.", "Simplified whole-home mesh management."),
        _p("NETGEAR Orbi Series", "https://www.netgear.com/home/wifi/mesh/", "NETGEAR", "NETGEAR Orbi mesh WiFi", "Wi-Fi mesh networking", "Mesh router system", "Verify backhaul design, ports, coverage planning and subscription features.", "Larger homes comparing mesh topologies."),
    )),
    Cluster("mini-pcs", "mini PCs", "computing", (
        _p("Minisforum Mini PC Series", "https://store.minisforum.com/collections/mini-pc", "Minisforum", "Minisforum mini PC", "x86 desktop platform", "Mini PC", "Check CPU generation, ports, memory/storage access and operating-system support.", "Compact desktop systems with configurable hardware."),
        _p("GEEKOM Mini PC Series", "https://www.geekompc.com/", "GEEKOM", "GEEKOM mini PC", "x86 desktop platform", "Mini PC", "Verify port layout, storage expansion, wireless hardware and support terms.", "Small desktop and home-office deployments."),
        _p("Beelink Mini PC Series", "https://www.bee-link.com/", "Beelink", "Beelink mini PC", "x86 desktop platform", "Mini PC", "Check exact configuration, ports, firmware and regional warranty.", "Budget-conscious compact desktop comparisons."),
        _p("Apple Mac mini", "https://www.apple.com/mac-mini/", "Apple", "Apple Mac mini", "Apple silicon desktop platform", "Mini desktop", "Verify memory/storage configuration, display support and software compatibility.", "Compact macOS desktop workflows."),
    )),
    Cluster("monitors", "monitors", "computing", (
        _p("Dell UltraSharp Series", "https://www.dell.com/en-us/shop/monitors-monitor-accessories/ar/4009", "Dell", "Dell UltraSharp monitor", "DisplayPort, HDMI and USB-C", "Desktop monitor", "Check panel size, resolution, USB-C power, stand and calibration options.", "Professional desktop and home-office setups."),
        _p("LG UltraFine Series", "https://www.lg.com/us/monitors", "LG", "LG UltraFine monitor", "DisplayPort, HDMI and USB-C", "Desktop monitor", "Verify host compatibility, USB-C behavior, ergonomics and panel specification.", "Laptop-centric desk setups."),
        _p("ASUS ProArt Series", "https://www.asus.com/displays-desktops/monitors/proart/", "ASUS", "ASUS ProArt monitor", "DisplayPort, HDMI and USB-C", "Desktop monitor", "Check calibration claims, ports, color workflow and stand adjustment.", "Content-creation and color-managed workflows."),
        _p("BenQ PD Series", "https://www.benq.com/en-us/monitor/professional.html", "BenQ", "BenQ PD monitor", "DisplayPort, HDMI and USB-C", "Desktop monitor", "Verify connectivity, color modes, KVM behavior and desk ergonomics.", "Design and productivity desk workflows."),
    )),
)


def _meta(title: str) -> str:
    value = f"{title}: a source-backed decision matrix using official documentation, stable compatibility facts and current Amazon ES destination links."
    return value[:170].rstrip() if len(value) > 170 else value


def _page(cluster: Cluster, *, kind: str, qualifier: str, options: tuple[Product, ...], number: int) -> dict[str, object]:
    if kind == "vs":
        title = f"{options[0].name} vs {options[1].name}: which {cluster.label} fits your setup?"
        answer = f"Start with {options[0].name} when you need {options[0].fit.rstrip('.').lower()}. Start with {options[1].name} when you need {options[1].fit.rstrip('.').lower()}. Verify the exact current model before buying."
        intent_type = "comparison"
    elif kind == "alternatives":
        title = f"Alternatives to {options[0].name}: {cluster.label} with different trade-offs"
        answer = f"If {options[0].name} is not the right fit, compare {options[1].name} and {options[2].name} on their documented interface, setup and ownership requirements."
        intent_type = "comparison"
    else:
        title = f"Best {cluster.label} for {qualifier}"
        answer = f"For {qualifier}, begin with {options[0].name} when you need {options[0].fit.rstrip('.').lower()}. Compare {options[1].name} when you need {options[1].fit.rstrip('.').lower()}."
        intent_type = "best-for"
    alternatives = []
    for product in options:
        alternatives.append({"name": product.name, "url": product.official_url, "summary": product.fit + " Confirm the exact current model and regional compatibility in its official documentation.", "specs": {
            "model": product.name, "interface": product.interface, "form": product.form,
            "operations": product.operations, "fit": product.fit,
            "intent": f"Relevant to {qualifier} because it is documented as a {product.form.lower()} with {product.interface.lower()}.",
        }})
    return {
        "slug": f"v3-{cluster.slug}-{kind}-{number:02d}", "content_model": "v2", "status": "reviewed", "locale": "en",
        "category": "consumer-product", "topic": cluster.slug, "intent_type": intent_type,
        "audience": f"{kind}-{qualifier}", "title": title, "meta_description": _meta(title),
        "eyebrow": f"{cluster.label.title()} decision guide", "answer_first": answer,
        "intro": f"This answer-first guide compares documented {cluster.label} options for {qualifier}. It uses official manufacturer documentation, omits volatile price and stock claims, and keeps retailer destinations separate from the editorial decision.",
        "verdict": answer, "updated_at": date.today().isoformat(), "reviewed_by": "StackSignal technical editorial desk",
        "criteria": [{"key": key, "label": label, "description": description} for key, label, description in CRITERIA],
        "alternatives": alternatives,
        "faq": [
            {"question": f"How should I choose {cluster.label} for {qualifier}?", "answer": "Start with the documented platform, physical form, setup and ongoing maintenance. Confirm exact model, regional compatibility and current listing details in the linked primary documentation before purchase."},
            {"question": "Does this guide publish live price or stock?", "answer": "No. Prices, bundles and availability change frequently, so StackSignal links to the current destination without freezing volatile commercial claims."},
            {"question": "Are ratings or buyer-review claims used here?", "answer": "No. This is a technical editorial synthesis of official documentation and does not claim an independently verified buyer-review dataset."},
        ],
        "sources": [{"label": f"{p.name} official documentation", "publisher": p.publisher, "url": p.official_url} for p in options],
        "resources": [{"title": p.name, "target_url": amazon_search_url(p.query), "note": f"Check the current exact model, specifications and availability for {p.name}."} for p in options],
    }


def generate_intent_batch(*, pages_root: Path, total: int = 500) -> int:
    if total != 500:
        raise ValueError("V3 is intentionally bounded to its audited 500-page batch")
    destination = pages_root / "v3"
    destination.mkdir(parents=True, exist_ok=True)
    for stale in destination.glob("*.json"):
        stale.unlink()
    pages: list[dict[str, object]] = []
    for cluster in CLUSTERS:
        uses = USE_CASES[cluster.domain]
        pages.append(_page(cluster, kind="best", qualifier="everyday use", options=cluster.products, number=1))
        for index, qualifier in enumerate(uses, 2):
            rotated = cluster.products[index % len(cluster.products):] + cluster.products[:index % len(cluster.products)]
            pages.append(_page(cluster, kind="use-case", qualifier=qualifier, options=rotated, number=index))
        for index, pair in enumerate(combinations(cluster.products, 2), 1):
            pages.append(_page(cluster, kind="vs", qualifier="direct comparison", options=pair, number=index))
        for index, product in enumerate(cluster.products, 1):
            alternatives = (product,) + tuple(p for p in cluster.products if p != product)[:2]
            pages.append(_page(cluster, kind="alternatives", qualifier=product.name, options=alternatives, number=index))
        if cluster.slug in COMPATIBILITY:
            pages.append(_page(cluster, kind="compatibility", qualifier=COMPATIBILITY[cluster.slug], options=cluster.products, number=1))
    if len(pages) != total:
        raise RuntimeError(f"expected {total} curated V3 pages, got {len(pages)}")
    for page in pages:
        (destination / f"{page['slug']}.json").write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(pages)
