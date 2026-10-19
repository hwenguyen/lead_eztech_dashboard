"""Script restore backup data into new Neon DB using SQLAlchemy bulk insert."""
import sys
import os
import time
import json
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv(".env.local")
load_dotenv(".env")

def restore_database(new_database_url: str):
    if not new_database_url:
        print("Error: DATABASE_URL not found.")
        sys.exit(1)

    if new_database_url.startswith("postgres://"):
        new_database_url = "postgresql://" + new_database_url[len("postgres://"):]
    if new_database_url.startswith("postgresql://") and not new_database_url.startswith("postgresql+psycopg2://"):
        new_database_url = "postgresql+psycopg2://" + new_database_url[len("postgresql://"):]

    print(f"Connecting to database: {new_database_url.split('@')[-1]}...")
    engine = create_engine(new_database_url)

    # 1. Initialize schema
    print("1. Ensuring schema and tables...")
    from database.models import Base, DimLead, FactLeadActivity, RawConversation
    import database.schema as schema_mod
    schema_mod.engine = engine
    Base.metadata.create_all(bind=engine)
    schema_mod.ensure_schema()
    print("-> Schema ready.")

    model_map = {
        'dim_leads': (DimLead, 'dim_leads_backup.pkl'),
        'fact_lead_activities': (FactLeadActivity, 'fact_lead_activities_backup.pkl'),
        'raw_conversations': (RawConversation, 'raw_conversations_backup.pkl'),
    }

    t0 = time.time()
    for table_name, (model_cls, pkl_file) in model_map.items():
        if not os.path.exists(pkl_file):
            print(f"Warning: file {pkl_file} not found, skipping.")
            continue

        print(f"Loading {table_name} from {pkl_file}...")
        df = pd.read_pickle(pkl_file)
        # Convert NaN to None for SQL NULL
        df = df.where(pd.notnull(df), None)
        records = df.to_dict(orient='records')
        total = len(records)
        print(f"-> Read {total} rows. Inserting into {table_name}...")

        chunk_size = 500
        with Session(engine) as session:
            # Check existing count
            existing = session.query(model_cls).count()
            if existing >= total:
                print(f"-> Table {table_name} already has {existing} rows, skipping insert.")
                continue
            elif existing > 0:
                print(f"-> Clearing {existing} existing rows in {table_name}...")
                session.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE"))
                session.commit()

            for i in range(0, total, chunk_size):
                chunk = records[i:i + chunk_size]
                session.bulk_insert_mappings(model_cls, chunk)
                session.commit()
                print(f"   Inserted {min(i + chunk_size, total)}/{total} rows...")

        print(f"-> Done inserting into {table_name}.")

    # Reset sequence IDs
    print("Resetting database sequence IDs...")
    with engine.begin() as conn:
        for t in ['dim_leads', 'fact_lead_activities', 'raw_conversations']:
            try:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), coalesce(max(id), 1)) FROM {t};"))
            except Exception as e:
                pass

    print(f"\nRESTORE COMPLETED SUCCESSFULLY in {time.time() - t0:.1f}s!")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else (os.getenv("NEW_DATABASE_URL") or os.getenv("DATABASE_URL"))
    restore_database(url)
