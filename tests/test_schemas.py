from app.schemas.common import CamelModel, Page


class Item(CamelModel):
    user_name: str


def test_page_shape_and_camel_case():
    p = Page[Item].build([Item(user_name="a")], total=21, page=2, size=10)
    assert p.model_dump(by_alias=True) == {
        "data": [{"userName": "a"}],
        "totalElements": 21,
        "totalPages": 3,
        "page": 2,
        "size": 10,
    }


def test_camel_model_accepts_both_names():
    assert Item.model_validate({"userName": "x"}).user_name == "x"
    assert Item(user_name="y").user_name == "y"
