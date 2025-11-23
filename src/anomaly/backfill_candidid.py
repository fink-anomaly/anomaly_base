import asyncio
import pandas as pd
import requests
import io
import re
from datetime import datetime

from sqlalchemy.orm import sessionmaker
from sqlmodel import create_engine, select
from astropy.time import Time


def get_fink_data(oids, chunk_limit=100):
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    filtered_oids = [oid for oid in oids if 'ZTF' in oid]
    if not filtered_oids:
        print("No matching ZTF objects found.")
        return pd.DataFrame()

    all_data = []
    print(f"Fetching Fink data for {len(filtered_oids)} objects...")
    for chunk in chunks(filtered_oids, chunk_limit):
        payload = {
            'objectId': ','.join(chunk),
            'columns': 'd:lc_features_g,d:lc_features_r,i:objectId,d:anomaly_score,i:candid,i:jd',
            'output-format': 'json'
        }
        try:
            r = requests.post('https://api.fink-portal.org/api/v1/objects', json=payload, timeout=60)
            if r.status_code != 200:
                print(f"Error {r.status_code}: {r.text[:200]}...")
                continue
            pdf = pd.read_json(io.BytesIO(r.content))
            all_data.append(pdf)
        except Exception as e:
            print(f"Request/Parsing failed for chunk: {e}")
            continue

    if all_data:
        return pd.concat(all_data, ignore_index=True)
    else:
        print("No data was retrieved from Fink.")
        return pd.DataFrame()


def get_jd_from_description(description: str) -> float | None:

    if not description:
        return None
    match = re.search(r"\*?\*?UTC\*?\*?:\s+([\d\-]+\s[\d:\.]+)", description)

    if not match:
        print(f"DEBUG: Could not find UTC timestamp in description: '{description[:150]}...'")
        return None
    utc_str = match.group(1).strip()
    dt_object = None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt_object = datetime.strptime(utc_str, fmt)
            break
        except ValueError:
            continue

    if not dt_object:
        print(f"DEBUG: Could not parse date string: '{utc_str}'")
        return None
    return Time(dt_object, format='datetime').jd


from database.settings import Settings
from models.base_types import reaction, ImageDocument


async def process_table(session, model, batch_size=100):
    """
    Generic function to backfill candid_id for a given table.
    """
    model_name = model.__tablename__
    print(f"\n--- Starting backfill for table: {model_name} ---")

    total_to_update = session.query(model).filter(model.candid_id.is_(None)).count()
    if total_to_update == 0:
        print(f"No records to update in {model_name}. All documents have a candid_id.")
        return

    print(f"Found {total_to_update} records in '{model_name}' to update.")
    processed_count = 0

    for offset in range(0, total_to_update, batch_size):
        print(f"\nProcessing batch {offset // batch_size + 1} for '{model_name}'...")
        batch_records = session.query(model).filter(model.candid_id.is_(None)).limit(batch_size).all()

        if not batch_records:
            break
        objid_to_jd = {}
        unique_ztf_ids = set()

        for record in batch_records:
            jd = None
            if model is ImageDocument:
                jd = get_jd_from_description(record.description)
            elif model is reaction:
                try:
                    dt = datetime.fromisoformat(record.changed_at)
                    jd = Time(dt, format='datetime').jd
                except (ValueError, TypeError):
                    print(f"Warning: Could not parse `changed_at` date: {record.changed_at}")
                    continue

            if jd:
                objid_to_jd[record.id] = {'ztf_id': record.ztf_id, 'jd': jd}
                unique_ztf_ids.add(record.ztf_id)

        if not unique_ztf_ids:
            print("No valid records with parseable dates in this batch. Skipping.")
            continue

        fink_df = get_fink_data(list(unique_ztf_ids))
        if fink_df.empty:
            print("Fink API returned no data for this batch. Skipping.")
            continue

        updates_made = 0
        for record in batch_records:
            if record.id not in objid_to_jd:
                continue

            local_data = objid_to_jd[record.id]
            ztf_id = local_data['ztf_id']
            local_jd = local_data['jd']
            object_alerts_df = fink_df[fink_df['i:objectId'] == ztf_id]
            if object_alerts_df.empty:
                continue
            time_diff = (object_alerts_df['i:jd'] - local_jd).abs()
            closest_alert_index = time_diff.idxmin()
            found_candid_id = object_alerts_df.loc[closest_alert_index, 'i:candid']
            record.candid_id = str(found_candid_id)
            updates_made += 1
        if updates_made > 0:
            print(f"Found {updates_made} candid_ids. Committing to database...")
            session.commit()
        else:
            print("Could not find matching candid_ids for this batch.")

        processed_count += len(batch_records)
        print(f"Processed {processed_count}/{total_to_update} records for '{model_name}'.")

    print(f"--- Backfill for table '{model_name}' complete! ---")


async def main():
    settings = Settings()
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as session:
        print(
            "IMPORTANT: Make sure you have added `candid_id` a nullable column to 'images' and 'reactions' tables first!")

        await process_table(session, ImageDocument)
        await process_table(session, reaction)


if __name__ == "__main__":
    asyncio.run(main())
