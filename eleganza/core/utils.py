from typing import Iterator, Sequence, TypeVar
from django.db.models import QuerySet

T = TypeVar('T')  # Generic type for querysets

def chunked_queryset(queryset: QuerySet[T], chunk_size: int) -> Iterator[Sequence[T]]:
    """
    Break a large queryset into memory-friendly chunks.
    
    Args:
        queryset: Django queryset to chunk
        chunk_size: Number of items per batch
        
    Yields:
        Lists of model instances
    
    Example:
        for batch in chunked_queryset(Product.objects.all(), 100):
            process_batch(batch)
    """
    start_pk = 0
    while True:
        # No need to order if using pk
        batch = list(queryset.filter(pk__gt=start_pk)[:chunk_size])
        if not batch:
            break
        yield batch
        start_pk = batch[-1].pk