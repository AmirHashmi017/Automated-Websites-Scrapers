import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://ucr.fbi.gov/crime-in-the-u.s/2019/crime-in-the-u.s.-2019/topic-pages/tables/table-1"

def build_driver():
    options = Options()
    options.add_argument("--start-maximized")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def to_number(text):
    """Convert string to float after removing commas and whitespace."""
    try:
        return float(text.replace(",", "").strip())
    except:
        return None

def scrape_fbi_crime(driver):
    driver.get(URL)
    time.sleep(5)  # wait for table to load

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    data = []

    for row in rows:
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            continue

        state = cells[0].text.strip()
        population = to_number(cells[1].text)
        violent_crime = to_number(cells[2].text)
        murder = to_number(cells[3].text)
        robbery = to_number(cells[4].text)
        property_crime = to_number(cells[5].text)

        data.append({
            "State": state,
            "Population": population,
            "ViolentCrime": violent_crime,
            "Murder": murder,
            "Robbery": robbery,
            "PropertyCrime": property_crime
        })

    return data

def main():
    driver = build_driver()
    try:
        data = scrape_fbi_crime(driver)
    finally:
        driver.quit()

    df = pd.DataFrame(data)
    df = df.drop_duplicates()
    df = df.dropna(subset=["State"])
    df.to_csv("fbi_crime_us.csv", index=False)

    print(f"Saved {len(df)} rows to fbi_crime_us.csv")
    print(df.head())

if __name__ == "__main__":
    main()