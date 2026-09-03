from dataclasses import dataclass

from app.retrieval.hybrid_search import _reciprocal_rank_fusion


@dataclass
class FakeHit:
    id: str
    payload: dict


def test_rrf_favors_items_ranked_highly_in_both_lists():
    dense_hits = [FakeHit("a", {}), FakeHit("b", {}), FakeHit("c", {})]
    sparse_hits = [FakeHit("b", {}), FakeHit("a", {}), FakeHit("d", {})]

    fused = _reciprocal_rank_fusion(dense_hits, sparse_hits)
    fused_ids = [item["id"] for item in fused]

    # "a" and "b" appear near top of both lists -> should outrank "c"/"d",
    # which only appear in one list each.
    assert fused_ids.index("a") < fused_ids.index("c")
    assert fused_ids.index("b") < fused_ids.index("d")


def test_rrf_includes_items_present_in_only_one_list():
    dense_hits = [FakeHit("a", {})]
    sparse_hits = [FakeHit("b", {})]

    fused = _reciprocal_rank_fusion(dense_hits, sparse_hits)
    fused_ids = {item["id"] for item in fused}

    assert fused_ids == {"a", "b"}
