import time
import pandas as pd
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://ucr.fbi.gov/crime-in-the-u.s/2019/crime-in-the-u.s.-2019/tables/table-5"

def build_driver():
    options = Options()
    options.add_argument("--start-maximized")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def clean_value(text):
    if not text or text.strip() == "":
        return 0
    clean_text = re.sub(r'[^\d]', '', text.strip())
    return int(clean_text) if clean_text else 0

def clean_state_name(text):
    return re.sub(r'\d+$', '', text.strip()).strip()

def scrape_fbi_crime(driver):
    print(f"Opening URL: {URL}")
    driver.get(URL)
    time.sleep(10)  

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    data = []
    current_state = ""

    print(f"Found {len(rows)} potential rows. Extracting data...")

    for row in rows:
        cells = row.find_elements(By.CSS_SELECTOR, "td, th")
        if not cells:
            continue

        first_cell = cells[0].text.strip()
        
        if first_cell and first_cell.isupper() and "TOTAL" not in first_cell and "AREA" not in first_cell:
           
            candidate = clean_state_name(first_cell)
            if len(candidate) > 2: 
                current_state = candidate

  
        is_total_row = False
        if first_cell == "State Total":
            is_total_row = True
        elif first_cell == "Total" and (current_state == "DISTRICT OF COLUMBIA" or current_state == "PUERTO RICO"):
            is_total_row = True

        if is_total_row and current_state:

            try:
                if len(cells) < 12:
                    continue

                population = clean_value(cells[2].text)
                violent_crime = clean_value(cells[3].text)
                robbery = clean_value(cells[6].text)
                property_crime = clean_value(cells[8].text)
                motor_vehicle_theft = clean_value(cells[11].text)

                data.append({
                    "State": current_state,
                    "Population": population,
                    "Violent Crime": violent_crime,
                    "Robbery": robbery,
                    "Property Crime": property_crime,
                    "Motor Vehicle Theft": motor_vehicle_theft
                })
            except Exception as e:
                continue

    return data

def main():
    driver = build_driver()
    try:
        data = scrape_fbi_crime(driver)
    finally:
        driver.quit()

    if not data:
        print("No data extracted. Please check selectors.")
        return

    df = pd.DataFrame(data)
    df = df.drop_duplicates(subset=["State"])
    df = df.sort_values("State")

    output_file = "fbi_crime_us.csv"
    df.to_csv(output_file, index=False)

    print(f"Successfully saved {len(df)} rows to {output_file}")
    print("\nPreview of the data:")
    print(df.head())
    print("\nSummary Statistics:")
    print(df.describe())

if __name__ == "__main__":
    main()
