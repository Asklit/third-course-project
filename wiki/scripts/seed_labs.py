from pymongo import MongoClient

from src.core.config import settings
from src.infrastructure.db.seed import seed_labs


def main() -> None:
    client = MongoClient(settings.mongo_url)
    collection = client[settings.mongo_db][settings.mongo_collection]
    collection.create_index("slug", unique=True)

    count = seed_labs(collection)
    print(f"Seeded labs: {count}")


if __name__ == "__main__":
    main()
