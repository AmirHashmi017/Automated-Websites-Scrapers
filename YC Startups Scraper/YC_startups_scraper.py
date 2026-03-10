import time
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager


URL = "https://www.ycombinator.com/companies"


def build_driver():
    options = Options()
    options.add_argument("--start-maximized")


    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    return driver


def scroll_page(driver, scrolls=15):
    """
    Scrolls the page and waits for new content to load.
    """
    last_height = driver.execute_script("return document.body.scrollHeight")
    
    for i in range(scrolls):
        print(f"Scrolling {i+1}/{scrolls}...")
        driver.execute_script(
            "window.scrollTo(0, document.body.scrollHeight);"
        )

        time.sleep(3)
        
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print("Reached bottom or no new content.")
            driver.execute_script("window.scrollBy(0, -200);")
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
        
        last_height = new_height


def scrape_companies(driver):
    companies = []

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/companies/']"))
        )
    except Exception as e:
        print(f"Error waiting for cards: {e}")
        return []

    cards = driver.find_elements(By.CSS_SELECTOR, "a[href^='/companies/']")
    print(f"Found {len(cards)} company cards.")

    for card in cards:
        try:
            # Extraction using specific selectors
            try:
                name = card.find_element(By.CSS_SELECTOR, "span[class*='_coName_']").text
            except:
                name = ""

            try:
                location = card.find_element(By.CSS_SELECTOR, "span[class*='_coLocation_']").text
            except:
                location = ""

            try:
                description = card.find_element(By.CSS_SELECTOR, "div.text-sm span").text
            except:
                description = ""

            try:
                batch = card.find_element(By.CSS_SELECTOR, "a[href*='batch='] span").text
            except:
                batch = ""

            try:
                tag_els = card.find_elements(By.CSS_SELECTOR, "a[href*='industry='] span")
                tags = ", ".join([el.text for el in tag_els])
            except:
                tags = ""

            link = card.get_attribute("href")

            companies.append({
                "name": name,
                "location": location,
                "description": description,
                "batch": batch,
                "tags": tags,
                "profile_link": link
            })

        except Exception as e:
            print(f"Error scraping a card: {e}")
            continue

    return companies


def clean_data(data):
    df = pd.DataFrame(data)
    print("Raw records:", len(df))

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["name", "profile_link"])
    df = df.dropna(subset=["name"])

    print("Cleaned records:", len(df))
    return df


def main():
    driver = build_driver()
    try:
        driver.get(URL)

        print("Waiting for page load...")
        time.sleep(5)

        scroll_page(driver, 10)
        data = scrape_companies(driver)
        
        if data:
            df = clean_data(data)
            df.to_csv("yc_companies_clean.csv", index=False)
            print("Saved to yc_companies_clean.csv")
        else:
            print("No data found.")
            
    finally:
        driver.quit()


if __name__ == "__main__":
    main()