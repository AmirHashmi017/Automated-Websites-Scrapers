import re, time, csv, os, argparse, logging, requests
from dataclasses import dataclass, fields, asdict
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException
)
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse, parse_qs

# ─── Config ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
URL = "https://www.volkswagen.de/de/haendlersuche.html?zoom-app=10"

def load_env(filepath):
    env = {}
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env[k.strip()] = v.strip()
    return env

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if not os.path.exists(env_path):
    env_path = ".env"
API_KEY = load_env(env_path).get("GOOGLE_MAPS_API_KEY")

# ─── Data ─────────────────────────────────────────────────────────────────────
@dataclass
class Dealer:
    name: str = ""
    address: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    website: str = ""
    latitude: float = None
    longitude: float = None

def save_csv(dealers, filename):
    if not dealers: return
    keys = [f.name for f in fields(Dealer)]
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for d in dealers:
            writer.writerow(asdict(d))

def geocode(address):
    if not API_KEY or not address: return None, None
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": API_KEY, "region": "de"}, timeout=10
        ).json()
        if r["status"] == "OK":
            loc = r["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception: pass
    return None, None

# ─── Driver ───────────────────────────────────────────────────────────────────
def build_driver(headless=False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=de-DE")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def jclick(driver, el):
    driver.execute_script("arguments[0].click();", el)

# ─── Steps ────────────────────────────────────────────────────────────────────
def accept_cookies(driver):
    try:
        btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "modalAcceptButton")))
        log.info("Accepting cookies...")
        jclick(driver, btn)
        time.sleep(2)
    except TimeoutException: pass

def load_and_search(driver, city):
    log.info(f"Loading {URL}...")
    driver.get(URL)
    time.sleep(6)
    accept_cookies(driver)

    try:
        inp = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[role='combobox']")))
    except TimeoutException:
        log.error("Search input not found"); return False

    log.info(f"Searching for: {city}")
    jclick(driver, inp)
    inp.send_keys(Keys.CONTROL + "a")
    inp.send_keys(Keys.BACKSPACE)
    inp.send_keys(city)
    time.sleep(2.5)

    # Try to click suggestion
    try:
        sugg_xpath = "//*[contains(@id, 'suggestion-') or contains(@class, 'suggestion')]//*[contains(text(), ', Deutschland')]"
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, sugg_xpath)))
        for s in driver.find_elements(By.XPATH, sugg_xpath):
            if s.is_displayed() and city.lower() in s.text.lower():
                log.info(f"Clicking suggestion: {s.text}")
                jclick(driver, s)
                time.sleep(8)
                return True
    except: pass

    log.warning("No suggestion clicked, pressing Enter")
    inp.send_keys(Keys.ENTER)
    time.sleep(8)
    return True

def get_contact_buttons(driver):
    """Get all visible 'Kontaktinformationen anzeigen' buttons, excluding footer/nav."""
    try:
        btns = driver.find_elements(By.XPATH, "//button[contains(@aria-label,'Kontaktinformationen')]")
        valid = []
        for b in btns:
            try:
                in_footer = driver.execute_script("return !!arguments[0].closest('footer, nav');", b)
                if not in_footer:
                    valid.append(b)
            except: pass
        return valid
    except: return []

def extract_coords(url):
    try:
        if not url: return None, None
        # Try destination param first
        qs = parse_qs(urlparse(url).query)
        dest = qs.get('destination', [None])[0]
        if dest:
            a, b = dest.split(','); return float(a), float(b)
        
        # Try @lat,long pattern (common in Google Maps links)
        m = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if m: return float(m.group(1)), float(m.group(2))
        
        # Try /lat,long/ pattern
        m = re.search(r'/(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if m: return float(m.group(1)), float(m.group(2))
    except: pass
    return None, None

def parse_contact_pane(driver, dealer_name):
    """
    Scrapes details from the open contact pane drawer.
    Uses reliable selectors based on diagnostic DOM analysis.
    """
    data = Dealer()
    data.name = dealer_name
    try:
        # Wait for any relevant contact link in the pane (tel, mailto, website)
        # We wait for a visible link that isn't in a footer/nav
        WebDriverWait(driver, 15).until(lambda d: any([
            el.is_displayed() and not d.execute_script("return !!arguments[0].closest('footer, nav, header');", el)
            for el in d.find_elements(By.XPATH, "//a[contains(@href,'tel:') or contains(@href,'mailto:') or contains(@aria-label,'Webseite')]")
        ]))
        
        log.info(f"    Parsing pane for: {dealer_name}")

        # ── Address ──
        try:
            # Look for address in the specific data-testid container
            addr_container = driver.find_element(By.CSS_SELECTOR, '[data-testid="address-information"]')
            data.address = addr_container.text.replace('\n', ', ').strip()
        except NoSuchElementException:
            try:
                addr_el = driver.find_element(By.XPATH, "//address[not(ancestor::footer or ancestor::nav)]")
                data.address = addr_el.text.replace('\n', ', ').strip()
            except: pass

        # ── Contact Links (Phone, Fax, Email, Website) ──
        # We iterate through all links in the pane and use SVG icon or href to identify them
        links = driver.find_elements(By.XPATH, "//div[contains(@class, 'sc-fKDIaf') or @data-testid='contact-information']//a[not(ancestor::footer or ancestor::nav)]")
        for link in links:
            try:
                # Use use-href to identify SVG icons (Phone, Fax, Internet, Mail)
                svg_use = link.find_element(By.TAG_NAME, "use").get_attribute("href")
                
                # Extract text within the link
                link_text = link.text.strip()
                if not link_text:
                    # Fallback to aria-label if text is empty
                    link_text = link.get_attribute("aria-label") or ""

                if "/Phone/" in svg_use:
                    data.phone = link_text.replace("Anrufen an:", "").strip()
                elif "/Fax/" in svg_use:
                    data.fax = link_text.strip()
                elif "/Mail/" in svg_use:
                    data.email = link.get_attribute("href").replace("mailto:", "").strip()
                elif "/Internet/" in svg_use:
                    data.website = link.get_attribute("href").strip()
            except:
                # Fallback to href patterns if SVG identification fails
                href = link.get_attribute("href") or ""
                if href.startswith("tel:"):
                    if not data.phone: data.phone = href.replace("tel:", "").strip()
                elif href.startswith("mailto:"):
                    if not data.email: data.email = href.replace("mailto:", "").strip()
                elif "Webseite" in (link.get_attribute("aria-label") or ""):
                    if not data.website: data.website = href.strip()

        # ── Lat/Lng from "route-planer" link ──
        try:
            route_link = driver.find_element(By.CSS_SELECTOR, 'a[data-testid="route-planer"]')
            lat, lng = extract_coords(route_link.get_attribute("href"))
            if lat: data.latitude, data.longitude = lat, lng
        except:
            # Fallback to any maps link
            try:
                maps = driver.find_element(By.XPATH, "//a[contains(@href,'google.com/maps')]")
                lat, lng = extract_coords(maps.get_attribute("href"))
                if lat: data.latitude, data.longitude = lat, lng
            except: pass

        # ── Close pane ──
        try:
            close = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(@aria-label,'Schließen') or contains(@aria-label,'Layer schließen') or contains(@aria-label,'schließen')]")
            ))
            jclick(driver, close)
        except:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1.5)

        return data

    except Exception as e:
        log.error(f"    parse_pane error: {e}")
        try: driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except: pass
        time.sleep(1)
        return None

# ─── Main scrape ──────────────────────────────────────────────────────────────
def scrape(city, output, headless):
    driver = build_driver(headless)
    try:
        if not load_and_search(driver, city):
            return

        seen = set()
        results = []
        no_new_streak = 0
        
        log.info("Starting extraction loop...")

        for cycle in range(500):  # More cycles for 200 items
            # 1. Count current cards in DOM
            try:
                cards = driver.find_elements(By.CSS_SELECTOR, '[data-testid="dealer-list-item"]')
                log.info(f"Cycle {cycle}: {len(cards)} cards visible in DOM. Total scraped: {len(results)}")
            except: cards = []

            btns = get_contact_buttons(driver)
            found_new = False

            for btn in btns:
                try:
                    if not btn.is_displayed(): continue
                    aria = (btn.get_attribute("aria-label") or "").strip()
                    key = aria or btn.text.strip()
                    if key in seen: continue

                    # Extract actual name from aria-label "Kontaktinformationen anzeigen <Dealer Name>"
                    d_name = aria.replace("Kontaktinformationen anzeigen", "").strip() or key
                    
                    # Scroll button into view and click
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(1)
                    jclick(driver, btn)
                    time.sleep(3)

                    d = parse_contact_pane(driver, d_name)
                    seen.add(key)

                    if d:
                        if d.address and (not d.latitude or not d.longitude):
                            log.info(f"      Attempting geocoding for {d.name}...")
                            d.latitude, d.longitude = geocode(d.address)
                        
                        results.append(d)
                        save_csv(results, output)
                        log.info(f"    ✓ Saved [{len(results)}] {d.name} (Coords: {d.latitude}, {d.longitude})")
                        found_new = True

                except Exception as e:
                    log.error(f"  Button error: {e}")

            # 2. Scroll the virtuoso container explicitly
            try:
                scroller = driver.find_element(By.CSS_SELECTOR, '[data-test-id="virtuoso-scroller"]')
                # Scroll down by a chunk
                driver.execute_script("arguments[0].scrollTop += 1200;", scroller)
                time.sleep(2)
            except Exception as e:
                log.warning(f"  Scroller not found, fallback to body scroll: {e}")
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)
                time.sleep(2)

            if found_new:
                no_new_streak = 0
            else:
                no_new_streak += 1

            # Be more patient for large lists
            if no_new_streak >= 12:
                log.info("No new dealers for 12 cycles. Finishing.")
                break

        log.info(f"✅ Done. Scraped {len(results)} dealers → {output}")

    finally:
        driver.quit()

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Volkswagen dealer scraper")
    ap.add_argument("--city",     default="Hessen")
    ap.add_argument("--output",   default="volkswagen_dealers.csv")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args()
    scrape(a.city, a.output, a.headless)
