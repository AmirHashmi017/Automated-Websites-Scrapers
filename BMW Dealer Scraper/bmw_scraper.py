import re, time, csv, os, argparse, logging
from dataclasses import dataclass, fields, asdict
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, StaleElementReferenceException,
    InvalidSessionIdException, WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
URL = "https://www.bmw.de/de/fastlane/dealer-locator.html"
CHROME_RESTART_EVERY = 20  


@dataclass
class Dealer:
    name: str = ""
    street: str = ""
    city: str = ""
    distance_km: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    website: str = ""

def build_driver(headless=False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=de-DE")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--js-flags=--max-old-space-size=512")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts
    )


def jclick(driver, el):
    driver.execute_script("arguments[0].click();", el)


def is_session_alive(driver):
    try:
        _ = driver.title
        return True
    except Exception:
        return False

def accept_cookies(driver):
    try:
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        jclick(driver, btn)
        time.sleep(1.5)
    except TimeoutException:
        pass

def load_and_search(driver, city: str, cookies_accepted: bool = False) -> bool:
    driver.get(URL)
    time.sleep(6)

    if not cookies_accepted:
        accept_cookies(driver)

    try:
        inp = WebDriverWait(driver, 40).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[role='combobox']:not([disabled])")
            )
        )
    except TimeoutException:
        log.error("Search input never appeared")
        return False

    jclick(driver, inp)
    time.sleep(0.3)
    inp.send_keys(Keys.CONTROL + "a")
    inp.send_keys(Keys.DELETE)
    inp.clear()
    time.sleep(0.2)
    inp.send_keys(city)
    time.sleep(3)

    clicked = False
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul[role='listbox'] li"))
        )
        time.sleep(0.6)
        items = driver.find_elements(By.CSS_SELECTOR, "ul[role='listbox'] li")
        items = [i for i in items if i.is_displayed() and i.text.strip()]
        if items:
            log.info(f"  Suggestion: '{items[0].text.strip()[:55]}'")
            jclick(driver, items[0])
            clicked = True
    except TimeoutException:
        pass

    if not clicked:
        inp.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.5)
        inp.send_keys(Keys.RETURN)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[id^='label_']"))
        )
        time.sleep(1.5)
        return True
    except TimeoutException:
        log.error("Dealer list never appeared")
        return False

def get_cards(driver):
    labels = driver.find_elements(By.CSS_SELECTOR, "[id^='label_']")
    cards = []
    for lbl in labels:
        try:
            btn = lbl.find_element(By.XPATH, "./ancestor::*[@role='button'][1]")
        except NoSuchElementException:
            btn = lbl
        cards.append((lbl, btn))
    return cards


def parse_label(el) -> dict:
    out = {"name": "", "street": "", "city": "", "distance_km": ""}
    try:
        lines = [l.strip() for l in el.text.strip().split("\n") if l.strip()]
        for line in lines:
            if "km" in line and len(line) < 15 and not out["distance_km"]:
                out["distance_km"] = line
            elif re.match(r"^\d{5}\s", line) and not out["city"]:
                out["city"] = line
            elif re.search(r"\d", line) and not out["street"] and out["name"]:
                out["street"] = line
            elif not out["name"] and "km" not in line:
                out["name"] = line
    except Exception:
        pass
    return out

def wait_for_detail(driver, timeout=12) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        labels = driver.find_elements(By.CSS_SELECTOR, "[id^='label_']")
        phones = driver.find_elements(By.XPATH, "//a[starts-with(@href,'tel:')]")
        emails = driver.find_elements(By.XPATH, "//a[starts-with(@href,'mailto:')]")
        if len(labels) == 1:
            return True
        if phones or emails:
            return True
        time.sleep(0.4)
    return False


def parse_detail(driver) -> dict:
    out = {"phone": "", "fax": "", "email": "", "website": ""}

    for xp in ["//a[starts-with(@href,'tel:')]",
                "//*[contains(text(),'Telefon') and not(ancestor::nav) and not(ancestor::footer)]"]:
        try:
            el = driver.find_element(By.XPATH, xp)
            href = el.get_attribute("href") or ""
            val = href.replace("tel:", "") if href.startswith("tel:") else el.text.replace("Telefon:", "")
            # Using a leading space to trick Excel into treating this as text
            out["phone"] = " " + val.strip() if val.strip() else ""
            if out["phone"]:
                break
        except NoSuchElementException:
            continue

    try:
        # Improved Fax search: look for elements containing 'Fax' then find a phone-like pattern in the container
        fax_labels = driver.find_elements(By.XPATH, "//*[contains(text(),'Fax') and not(ancestor::nav) and not(ancestor::footer)]")
        for label in fax_labels:
            # Check the element itself and its parent for the actual number
            container_text = label.find_element(By.XPATH, "./..").text
            # Regex for international phone/fax numbers
            match = re.search(r"Fax[:\s]*([\+\d\s\-\.\(\)/]{7,})", container_text, re.IGNORECASE)
            if match:
                fax_val = match.group(1).strip()
                out["fax"] = " " + fax_val # Leading space for Excel
                break
    except Exception:
        pass

    try:
        el = driver.find_element(By.XPATH, "//a[starts-with(@href,'mailto:')]")
        out["email"] = el.get_attribute("href").replace("mailto:", "").strip()
    except NoSuchElementException:
        pass

    try:
        blacklist = ["facebook.com", "instagram.com", "youtube.com", "twitter.com", "linkedin.com", "here.com", "google.com"]
        links = driver.find_elements(By.XPATH, "//a[starts-with(@href,'http')]")
        
        # Priority 1: Link text contains "Website besuchen"
        for a in links:
            txt = a.text.lower()
            href = a.get_attribute("href") or ""
            if "website besuchen" in txt:
                if not any(b in href.lower() for b in blacklist):
                    out["website"] = href
                    break
        
        # Priority 2: Any link not in blacklist and not containing 'bmw' in a way that suggests it's the main site
        if not out["website"]:
            for a in links:
                href = a.get_attribute("href") or ""
                if len(href) > 12 and not any(b in href.lower() for b in blacklist) and "bmw.de" not in href:
                    out["website"] = href
                    break
    except Exception:
        pass

    return out

def save_csv(dealers: list, output: str):
    """Write all dealers to CSV immediately."""
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[x.name for x in fields(Dealer)])
        writer.writeheader()
        writer.writerows(asdict(d) for d in dealers)


def load_existing(output: str) -> set:
    """
    Load already-scraped dealer keys from existing CSV.
    Key = (name, street) — used to skip on resume.
    """
    done = set()
    if not os.path.exists(output):
        return done
    try:
        with open(output, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["name"].strip().lower(), row["street"].strip().lower())
                done.add(key)
        log.info(f"Resuming: {len(done)} dealers already in '{output}'")
    except Exception:
        pass
    return done

def scrape_dealer(driver, city: str, idx: int, info: dict,
                  total: int, cookies_accepted: bool) -> tuple[Dealer, bool]:
    """
    Returns (Dealer, cookies_still_accepted).
    Reloads page, clicks card at idx, returns parsed Dealer.
    """
    if idx > 0:
        if not load_and_search(driver, city, cookies_accepted=cookies_accepted):
            log.warning("  Page reload failed")
            return Dealer(**info), cookies_accepted

    cards = get_cards(driver)
    if idx >= len(cards):
        log.warning(f"  Only {len(cards)} cards, need {idx}")
        return Dealer(**info), cookies_accepted

    lbl, btn = cards[idx]
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        jclick(driver, btn)
    except StaleElementReferenceException:
        cards = get_cards(driver)
        if idx < len(cards):
            jclick(driver, cards[idx][1])
        else:
            return Dealer(**info), cookies_accepted

    if not wait_for_detail(driver, timeout=12):
        log.warning("  Detail panel didn't appear")
        return Dealer(**info), cookies_accepted

    contact = parse_detail(driver)

    try:
        detail_labels = driver.find_elements(By.CSS_SELECTOR, "[id^='label_']")
        if detail_labels:
            fresh = parse_label(detail_labels[0])
            info = {k: fresh[k] or info[k] for k in info}
    except Exception:
        pass

    return Dealer(**info, **contact), cookies_accepted

def scrape(city: str, output: str, headless: bool):
    done_keys = load_existing(output)
    existing_dealers = []
    if done_keys:
        with open(output, newline="", encoding="utf-8") as f:
            existing_dealers = [Dealer(**row) for row in csv.DictReader(f)]

    log.info(f"Discovering dealers for: {city}")
    driver = build_driver(headless)
    cookies_accepted = False

    try:
        if not load_and_search(driver, city, cookies_accepted=False):
            log.error("Initial search failed.")
            return
        cookies_accepted = True

        cards = get_cards(driver)
        total = len(cards)
        log.info(f"Found {total} dealers total")

        if total == 0:
            return

        queue = [parse_label(lbl) for lbl, _ in cards]
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    dealers = existing_dealers[:]

    driver = build_driver(headless)
    cookies_accepted = False
    driver_use_count = 0

    try:
        for idx in range(total):
            info = queue[idx]
            key = (info["name"].strip().lower(), info["street"].strip().lower())

            if key in done_keys:
                log.info(f"[{idx+1}/{total}] SKIP (already scraped): {info['name']}")
                continue

            log.info(f"[{idx+1}/{total}] {info['name']} | {info['distance_km']}")

            if driver_use_count > 0 and driver_use_count % CHROME_RESTART_EVERY == 0:
                log.info(f"  ♻ Restarting Chrome (every {CHROME_RESTART_EVERY} dealers) …")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(2)
                driver = build_driver(headless)
                cookies_accepted = False
                driver_use_count = 0

            try:
                if driver_use_count == 0:
                    if not load_and_search(driver, city, cookies_accepted=False):
                        log.warning("  Search failed after Chrome restart")
                        dealers.append(Dealer(**info))
                        save_csv(dealers, output)
                        driver_use_count += 1
                        continue
                    cookies_accepted = True

                d, cookies_accepted = scrape_dealer(
                    driver, city, idx, info, total, cookies_accepted
                )
                dealers.append(d)
                done_keys.add(key)
                log.info(f"  ✓ {d.name} | {d.phone} | {d.email}")

            except (InvalidSessionIdException, WebDriverException) as e:
                log.error(f"  Browser error: {e.__class__.__name__} — restarting Chrome")
                dealers.append(Dealer(**info))
                save_csv(dealers, output)
                done_keys.add(key)
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(3)
                driver = build_driver(headless)
                cookies_accepted = False
                driver_use_count = 0
                continue

            except Exception as e:
                log.error(f"  Unexpected error: {e}")
                dealers.append(Dealer(**info))

            save_csv(dealers, output)
            driver_use_count += 1

    except KeyboardInterrupt:
        log.info("\n⚠ Interrupted by user — progress saved to CSV")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    seen = {}
    for d in dealers:
        key = (d.name.strip().lower(), d.street.strip().lower())
        if key not in seen:
            seen[key] = d
        else:
            s1 = sum(1 for v in asdict(seen[key]).values() if v)
            s2 = sum(1 for v in asdict(d).values() if v)
            if s2 > s1:
                seen[key] = d

    unique = list(seen.values())
    save_csv(unique, output)

    log.info(f"\n✅ Done! {len(unique)} unique dealers saved to '{output}'")
    print(f"\n{'='*72}")
    print(f"{'NAME':<36} {'PHONE':<22} DISTANCE")
    print(f"{'='*72}")
    for d in unique:
        print(f"{d.name[:35]:<36} {d.phone[:21]:<22} {d.distance_km}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city",     default="Hamburg")
    ap.add_argument("--output",   default="bmw_dealers.csv")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args()
    scrape(a.city, a.output, a.headless)