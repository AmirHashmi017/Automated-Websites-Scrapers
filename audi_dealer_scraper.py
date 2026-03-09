import time
import csv
import argparse
import logging
from dataclasses import dataclass, fields, asdict

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

URL = "https://www.audi.de/de/haendlersuche/"


@dataclass
class AudiDealer:
    name: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    services: str = ""
    distance_km: str = ""


def build_driver(headless: bool = False) -> webdriver.Chrome:
    options = Options()

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    )

    if headless:
        options.add_argument("--headless=new")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_window_size(1400, 900)
    return driver


def safe_text(driver, by: By, selector: str) -> str:
    try:
        return driver.find_element(by, selector).text.strip()
    except NoSuchElementException:
        return ""


def accept_cookies(driver: webdriver.Chrome):
    
    cookie_selectors = [
        "#ensCancel",                          
        "#ensAcceptAll",                      
        "button[aria-label='Alle akzeptieren']",
        "button[id*='ensCancel']",
        "button[id*='ensAccept']",
        "button[data-testid='uc-accept-all-button']",
        "#onetrust-accept-btn-handler",
        "button[id*='accept']",
        "button[class*='accept']",
    ]
    for selector in cookie_selectors:
        try:
            btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            driver.execute_script("arguments[0].click();", btn)
            log.info(f"Cookie banner dismissed via: {selector}")
            time.sleep(1.5)
            return
        except TimeoutException:
            continue
    log.info("No cookie banner found (or already accepted).")


def accept_google_maps_consent(driver: webdriver.Chrome):
    try:
        log.info("Looking for Google Maps / in-page consent popup...")

        confirm_btn = None
        for xpath in [
            "//*[normalize-space(text())='Best\u00e4tigen']",
            "//*[normalize-space(.)='Best\u00e4tigen']",
            "//button[@id='confirm-button']",
        ]:
            try:
                confirm_btn = WebDriverWait(driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                log.info(f"Found 'Best\u00e4tigen' via: {xpath}")
                break
            except TimeoutException:
                continue

        if not confirm_btn:
            log.info("No Google Maps consent popup found — skipping.")
            return

        

        toggled = False

        toggle_js = """
        function findToggle(root) {
            var el = root.querySelector(
                'input[type="checkbox"]:not([disabled]), [role="switch"], '
                + '[class*="toggle"]:not([disabled]), [class*="switch"]:not([disabled]), '
                + '[class*="slider"]:not([disabled])'
            );
            if (el) return el;
            var nodes = root.querySelectorAll('*');
            for (var i = 0; i < nodes.length; i++) {
                if (nodes[i].shadowRoot) {
                    var found = findToggle(nodes[i].shadowRoot);
                    if (found) return found;
                }
            }
            return null;
        }
        return findToggle(document);
        """
        try:
            toggle_el = driver.execute_script(toggle_js)
            if toggle_el:
                driver.execute_script("arguments[0].click();", toggle_el)
                log.info("Strategy A: clicked toggle via JS shadow-DOM search.")
                time.sleep(1)
                toggled = True
        except Exception as e:
            log.debug(f"Strategy A failed: {e}")

        if not toggled:
            for xpath in [
                "//*[contains(text(),'Einwilligung erteilen')]",
                "//*[contains(.,'Einwilligung erteilen')]",
            ]:
                try:
                    label = driver.find_element(By.XPATH, xpath)
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", label)
                    time.sleep(0.3)
                    ActionChains(driver).move_to_element(label).click().perform()
                    log.info(f"Strategy B: ActionChains click on consent label.")
                    time.sleep(1)
                    toggled = True
                    break
                except Exception as e:
                    log.debug(f"Strategy B failed: {e}")

        if not toggled:
            try:
                labels = driver.find_elements(
                    By.XPATH,
                    "//label[.//input[@type='checkbox']] | "
                    "//label[contains(@class,'toggle') or contains(@class,'switch')] | "
                    "//span[contains(text(),'Einwilligung')] | "
                    "//*[contains(@class,'sc-fzqPZZ')] "
                )
                for lbl in labels:
                    if lbl.is_displayed():
                        driver.execute_script("arguments[0].click();", lbl)
                        log.info("Strategy C: clicked toggle element.")
                        time.sleep(1)
                        toggled = True
                        break
            except Exception as e:
                log.debug(f"Strategy C failed: {e}")

        if not toggled:
            log.warning(
                "Could not click Maps toggle. Check maps_consent_dump.html "
                "for the exact toggle element selector."
            )

        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", confirm_btn)
        log.info("Clicked 'Best\u00e4tigen' — Google Maps consent done.")
        time.sleep(2)

    except Exception as e:
        log.warning(f"Google Maps consent handler error: {e}")



def search_location(driver: webdriver.Chrome, location: str):
    log.info(f"Searching for location: {location}")

    input_selectors = [
        "input[placeholder*='suchen']",
        "input[placeholder*='search']",
        "input[placeholder*='Stadt']",
        "input[placeholder*='city']",
        "input[type='search']",
        "input[type='text']",
    ]

    try:
        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input#search-dealer-field"))
        )
        log.info("Found search input: input#search-dealer-field")
    except TimeoutException:
        for sel in input_selectors:
            try:
                search_input = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                log.info(f"Found search input with fallback: {sel}")
                break
            except TimeoutException:
                continue

    if not search_input:
        log.error("Could not find search input field!")
        return

    search_input.click()
    time.sleep(0.5)
    search_input.clear()
    search_input.send_keys(location)
    time.sleep(3.0)  

    suggestion_selector = f"button[aria-label*='select {location}']"
    try:
        suggestion = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, suggestion_selector))
        )
        log.info(f"Found suggestion: '{suggestion.text.strip()}'")
        driver.execute_script("arguments[0].click();", suggestion)
        log.info("Clicked suggestion.")
        clicked = True
    except Exception:
        log.info("Specific suggestion button not found, trying general pac-item...")
        suggestion_selectors = [
            ".pac-item",
            "div[class*='pac-item']",
        ]
        for sel in suggestion_selectors:
            try:
                suggestions = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, sel))
                )
                if suggestions:
                    visible = [s for s in suggestions if s.is_displayed()]
                    if visible:
                        log.info(f"Found suggestion via {sel}")
                        driver.execute_script("arguments[0].click();", visible[0])
                        clicked = True
                        break
            except Exception:
                continue

    if not clicked:
        log.warning("No suggestion clicked — trying keyboard fallback.")
        search_input.send_keys(Keys.ARROW_DOWN)
        time.sleep(0.5)
        search_input.send_keys(Keys.RETURN)

    time.sleep(4.0)

def get_dealer_list_items(driver: webdriver.Chrome) -> list:
    """Return all clickable dealer cards in the result list."""
    selectors = [
        "div[role='button'][class*='SearchResultsEntry__DealerCardName']",
        "div[class*='SearchResultsEntry__DealerCard']",
        "[data-testid*='dealer-card']",
    ]
    for sel in selectors:
        items = driver.find_elements(By.CSS_SELECTOR, sel)
        items = [i for i in items if i.is_displayed()]
        if items:
            log.info(f"Found {len(items)} dealer cards via: {sel}")
            return items

    log.warning("Could not find dealer list items.")
    return []


def get_distance_from_card(item) -> str:
    for sel in [
        "span[class*='SearchResultsEntry__Distance']",
        "div[class*='distance']",
        "[class*='km']",
        "span[class*='info']",
    ]:
        try:
            el = item.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text and any(char.isdigit() for char in text):
                return text
        except NoSuchElementException:
            continue
    return ""


def scrape_dealer_detail(driver: webdriver.Chrome) -> AudiDealer:
    """Scrape the detail panel (name, address, phone, email, services)."""
    dealer = AudiDealer()
    time.sleep(2)

    name_selectors = [
        "h2[class*='SearchResultsEntry__DealerCardName']",
        "p[class*='SearchResultsEntry__DealerCardName']",
        "h2",
        "h1"
    ]
    for sel in name_selectors:
        text = safe_text(driver, By.CSS_SELECTOR, sel)
        if text and len(text) > 3 and "Zurück" not in text and "Partner Details" not in text:
            dealer.name = text
            break
   
    if not dealer.name:
        try:
            container = driver.find_element(By.CSS_SELECTOR, ".DesktopDealerDetails__DealerDetailsContainer-sc-d70ec307-0")
            lines = [line.strip() for line in container.text.split('\n') if line.strip()]
            filtered = [l for l in lines if "Zurück" not in l and "Partner Details" not in l]
            if filtered:
                dealer.name = filtered[0]
        except Exception:
            pass

    tag_selectors = [
        "li[class*='ServiceItem']",
        "span[class*='Badge']",
        "span[class*='Tag']",
        "div[class*='ServiceList'] p",
        "span[class*='Service']",
    ]
    all_tags = []
    for sel in tag_selectors:
        elements = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in elements:
            t = el.text.strip()
            if t and t not in all_tags and len(t) < 40:
                all_tags.append(t)
    
    if all_tags:
        dealer.services = ", ".join(all_tags)


    for sel in ["a[href*='maps/dir/']", "[class*='address']", "address"]:
        text = safe_text(driver, By.CSS_SELECTOR, sel)
        if text:
            dealer.address = text.replace("\n", ", ")
            break

    for sel in ["a[href^='tel:']"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            dealer.phone = el.get_attribute("href").replace("tel:", "").strip()
            if dealer.phone: break
        except NoSuchElementException: continue

    for sel in ["a[href^='mailto:']"]:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            dealer.email = el.get_attribute("href").replace("mailto:", "").strip()
            if dealer.email: break
        except NoSuchElementException: continue

    log.info(f"  Name    : {dealer.name}")
    log.info(f"  Address : {dealer.address}")
    log.info(f"  Phone   : {dealer.phone}")
    log.info(f"  Email   : {dealer.email}")
    log.info(f"  Services: {dealer.services}")
    return dealer


def go_back_to_results(driver: webdriver.Chrome):
    back_selectors = [
        "button[aria-label='close dealer details']",
        "button[class*='close']",
        "a[class*='back']",
        "button[class*='back']",
    ]
    for sel in back_selectors:
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
            )
            driver.execute_script("arguments[0].click();", btn)
            log.info("Clicked back button.")
            time.sleep(2)
            return
        except TimeoutException:
            continue

    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//*[contains(text(),'Back') or contains(text(),'Zurück') "
                "or contains(text(),'Ergebnisse')]"
            ))
        )
        btn.click()
        log.info("Clicked back button via XPath.")
        time.sleep(2)
        return
    except TimeoutException:
        pass

    log.warning("Back button not found — using browser back().")
    driver.back()
    time.sleep(2.5)



def scrape(location: str, output: str, headless: bool = False):
    driver = build_driver(headless=headless)
    dealers: list[AudiDealer] = []

    try:
        log.info(f"Opening: {URL}")
        driver.get(URL)
        time.sleep(5)
        accept_cookies(driver)
        accept_google_maps_consent(driver)
        search_location(driver, location)

        time.sleep(3)

        items = get_dealer_list_items(driver)
        n = len(items)
        log.info(f"Total dealers to scrape: {n}")

        if n == 0:
            log.error("No dealers found. Check if the page loaded correctly.")
            return

        for i in range(n):
            log.info(f"\n── Dealer {i+1}/{n} ──────────────────────────")

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='SearchResultsEntry__DealerCard']"))
                )
                items = get_dealer_list_items(driver)
            except TimeoutException:
                log.warning("Results list did not reappear. Attempting to scroll or wait...")
                time.sleep(5)
                items = get_dealer_list_items(driver)

            if not items or i >= len(items):
                log.warning(f"Item index {i} invalid (found {len(items)} items). Stopping.")
                break

            item = items[i]
            distance = get_distance_from_card(item)

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", item)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", item)
 
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='close dealer details']"))
                )
            except Exception as e:
                log.warning(f"Could not open dealer {i+1}: {e}")

                try:
                    time.sleep(2)
                    driver.execute_script("arguments[0].click();", item)
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button[aria-label='close dealer details']"))
                    )
                except Exception:
                    continue


            dealer = scrape_dealer_detail(driver)
            dealer.distance_km = distance
            dealers.append(dealer)


            go_back_to_results(driver)
            time.sleep(2)

    except Exception as e:
        log.error(f"Unhandled error: {e}", exc_info=True)
    finally:
        driver.quit()

    if not dealers:
        log.warning("No dealers were scraped.")
        return

    fieldnames = [f.name for f in fields(AudiDealer)]
    log.info(f"\nTotal dealers scraped: {len(dealers)}")

    if output.endswith(".xlsx"):
        try:
            import pandas as pd
            df = pd.DataFrame([asdict(d) for d in dealers], columns=fieldnames)
            df.to_excel(output, index=False)
            log.info(f"Saved → {output}")
        except ImportError:
            log.error("pandas not installed. Saving as CSV instead.")
            output = output.replace(".xlsx", ".csv")
            with open(output, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows([asdict(d) for d in dealers])
            log.info(f"Saved → {output}")

    elif output.endswith(".csv"):
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows([asdict(d) for d in dealers])
        log.info(f"Saved → {output}")

    else:
        print("\n" + "=" * 60)
        for d in dealers:
            for k, v in asdict(d).items():
                print(f"  {k:15}: {v}")
            print("-" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audi Dealer Scraper")
    parser.add_argument(
        "--location",
        default="North Rhine-Westphalia",
        help="Location to search (default: North Rhine-Westphalia)",
    )
    parser.add_argument(
        "--output",
        default="audi_dealers.csv",
        help="Output file: .csv or .xlsx (default: audi_dealers.csv)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode",
    )
    args = parser.parse_args()

    scrape(
        location=args.location,
        output=args.output,
        headless=args.headless,
    )