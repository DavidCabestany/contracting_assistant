"""This module provides a DynamoDB class that implements a singleton pattern for interacting with AWS DynamoDB tables. The class includes methods for scanning items and inserting new items into the table."""

from abc import ABC
from typing import Dict, List

import boto3
from botocore.config import Config
from logger import SingletonLogger

logger = SingletonLogger().get_logger()


class DynamoDB(ABC):
    """A singleton class for interacting with a DynamoDB table.

    This class provides methods to initialize a connection to a specified
    DynamoDB table, perform scan operations to retrieve all items, and
    insert new items into the table. The singleton pattern ensures that only one
    instance of the class is created and reused throughout the application.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one instance of the class is created."""
        if cls._instance is None:
            cls._instance = super(DynamoDB, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of DynamoDB, initializing if necessary.

        :param table_name: The name of the DynamoDB table to interact with.
        :param region_name: The AWS region name. Defaults to "us-east-1".
        :return: The singleton instance of the DynamoDB class.
        """
        instance = cls._instance or cls()
        if not hasattr(instance, "initialized"):
            instance.__init__()
        return instance

    def __init__(self, table_name: str, region_name: str = "us-east-1"):
        """Initialize the DynamoDB client with the specified table and region.

        Args:
            table_name (str): The name of the DynamoDB table to interact with.
            region_name (str, optional): The AWS region name. Defaults to "us-east-1".
        """
        if not hasattr(self, "initialized"):
            logger.info(
                f"Initializing DynamoDB client for table: {table_name} in region: {region_name}"
            )

            boto_config = Config(
                retries={"max_attempts": 3}, max_pool_connections=50
            )
            self.dynamo_db_client = boto3.resource(
                "dynamodb", region_name=region_name, config=boto_config
            )
            self.table = self.dynamo_db_client.Table(table_name)
            self.table_name = table_name

            logger.debug(
                f"DynamoDB client initialized with config: {boto_config}"
            )
            logger.info("DynamoDB client initialization complete")
            self.initialized = True

    def scan(self) -> List[Dict[str, str]]:
        """Performs a paginated scan operation on the specified DynamoDB table to retrieve all items.

        :return: A list of dictionaries, where each dictionary represents an item in the table.
        """
        try:
            response = self.table.scan()
            items = response.get("Items", [])

            while "LastEvaluatedKey" in response:
                logger.info(
                    f"Fetching next page of results from table: {self.table_name}"
                )
                response = self.table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))

            logger.info(
                f"Scan successful for table: {self.table_name}, retrieved {len(items)} items."
            )
            return items
        except Exception as e:
            logger.error(f"Error scanning table {self.table_name}: {str(e)}")
            return []

    def put(self, item_data: Dict[str, str]):
        """Put a document into DynamoDB.

        Args:
            item_data (Dict[str, str]): The document data to be inserted.

        Raises:
            Exception: If there's an error during the insertion process.
        """
        try:
            self.table.put_item(Item=item_data)

        except Exception as e:
            logger.error(f"Error putting document into DynamoDB: {str(e)}")
            logger.debug(f"Document that failed to be put: {item_data}")
            raise
