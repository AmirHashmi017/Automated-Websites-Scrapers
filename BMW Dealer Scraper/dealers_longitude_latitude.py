import csv
import os
import re
import time
import requests

def load_env(filepath):
    env = {}
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    env[key.strip()] = value.strip()
    return env

def geocode_address(api_key, street, zip_code, city):
    full_address = f"{street}, {zip_code} {city}, Germany"
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": full_address,
        "key": api_key,
        "region": "de"
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
        else:
            error_msg = data.get("error_message", "No detailed error message provided.")
            print(f"  Geocoding failed for {full_address}: {data['status']}")
            print(f"  Error Detail: {error_msg}")
    except Exception as e:
        print(f"  Error geocoding {full_address}: {e}")
    
    return None, None

def migrate(input_csv, output_csv, api_key):
    if not os.path.exists(input_csv):
        print(f"Error: {input_csv} not found.")
        return

    with open(input_csv, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fieldnames = reader.fieldnames
    idx = fieldnames.index('city')
    new_fieldnames = fieldnames[:idx+1] + ['zip_code'] + fieldnames[idx+1:] + ['latitude', 'longitude']
    
    print(f"Migrating {len(rows)} dealers...")
    
    updated_rows = []
    for i, row in enumerate(rows):
        city_field = row.get('city', '')
        match = re.match(r"^(\d{5})\s+(.*)$", city_field.strip())
        
        if match:
            zip_code = match.group(1)
            city_name = match.group(2)
        else:
            zip_code = ""
            city_name = city_field

        print(f"[{i+1}/{len(rows)}] Geocoding: {row['name']} | {zip_code} {city_name}")
        
        lat, lng = geocode_address(api_key, row['street'], zip_code, city_name)
        
        row['zip_code'] = zip_code
        row['city'] = city_name
        row['latitude'] = lat
        row['longitude'] = lng
        updated_rows.append(row)
        
        time.sleep(0.1)

    with open(output_csv, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    print(f"Successfully migrated data to {output_csv}")

if __name__ == "__main__":
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(env_path):
        env_path = ".env" 
        
    config = load_env(env_path)
    API_KEY = config.get("GOOGLE_MAPS_API_KEY")

    if not API_KEY:
        print("Error: GOOGLE_MAPS_API_KEY not found in .env")
    else:
        input_file = "bmw_dealers.csv"
        output_file = "bmw_dealers_enhanced.csv"
        migrate(input_file, output_file, API_KEY)
