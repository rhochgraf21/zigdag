from zigdag import verifies
from zigdag.core.effects import IO_GROUP, Effect, expand, phrase, resource_container


@verifies("zigdag.core.vocabulary.effects#define")
def test_the_effect_names_are_closed_and_io_is_their_only_group():
    assert expand([Effect("io"), Effect("time")]) == IO_GROUP | {"time"}
    assert resource_container(Effect("shop.orders_db.write")) == "shop.orders_db"
    assert resource_container(Effect("write")) is None
    assert phrase(Effect("read")) == "reading files"
    assert phrase(Effect("shop.orders_db.write")) == "writing to the orders db"
    assert phrase(Effect("verus.run")) == "the verus.run effect"
