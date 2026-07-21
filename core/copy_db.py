from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
# MongoDB Connection URL
MONGO_URL = os.getenv("MONGO_URL")

SOURCE_DB = "UPSTOX_APP"
TARGET_DB = "UPSTOX_APP_TEST"


def copy_database():
    client = MongoClient(MONGO_URL)

    source_db = client[SOURCE_DB]
    target_db = client[TARGET_DB]

    print(f"Copying '{SOURCE_DB}' -> '{TARGET_DB}'")

    # Drop existing target database (optional)
    client.drop_database(TARGET_DB)
    target_db = client[TARGET_DB]

    collections = source_db.list_collection_names()

    if not collections:
        print("Source database is empty.")
        return

    for collection_name in collections:
        print(f"Copying collection: {collection_name}")

        source_collection = source_db[collection_name]
        target_collection = target_db[collection_name]

        documents = list(source_collection.find())

        if documents:
            target_collection.insert_many(documents)
            print(f"  Copied {len(documents)} documents")
        else:
            print("  Collection is empty")

    print("\nDatabase copy completed successfully!")


if __name__ == "__main__":
    copy_database()