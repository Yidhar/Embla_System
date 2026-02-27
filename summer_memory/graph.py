
try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable, AuthError
except ImportError:
    GraphDatabase = None  # type: ignore[assignment,misc]
    ServiceUnavailable = Exception  # type: ignore[assignment,misc]
    AuthError = Exception  # type: ignore[assignment,misc]


class Graph:
    def __init__(self, uri: str, user: str, password: str):
        if GraphDatabase is None:
            raise RuntimeError("neo4j 未安装，请运行 pip install neo4j 或启用远程记忆服务")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def check_connection(self) -> bool:
        """Verifies the connection to the database and returns True if successful."""
        try:
            self.driver.verify_connectivity()
            return True
        except (ServiceUnavailable, AuthError):
            return False

    def close(self) -> None:
        """Close underlying Neo4j driver."""
        try:
            if getattr(self, "driver", None) is not None:
                self.driver.close()
        except Exception:
            # Best-effort close.
            return
