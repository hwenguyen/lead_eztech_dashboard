from database.db import engine, Base
from database.models import DimLead, FactLeadActivity, RawConversation

print("Dropping database tables...")
Base.metadata.drop_all(bind=engine)
print("Tables dropped successfully!")

print("Creating database tables...")
Base.metadata.create_all(bind=engine)
print("Tables created successfully. Database is clean!")
