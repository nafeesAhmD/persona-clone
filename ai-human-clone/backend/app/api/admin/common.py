from typing import Annotated

from fastapi import Query

# Pagination for every admin list: default 20, at most 100 rows per page.
PageNumber = Annotated[int, Query(ge=1, le=100_000)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
Search = Annotated[str | None, Query(max_length=100)]
