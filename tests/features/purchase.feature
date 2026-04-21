Feature: Wishlist item purchase rules
  Anyone on the family can mark a wishlist item as purchased except the
  list's owner or managers (no spoilers). A purchaser may toggle their
  own purchase back off. Once an item is purchased, nobody else may
  overwrite that purchase. The "Purchased by" badge is shown to everyone
  on the list except the list owner/managers.

  Scenario: Non-owner can mark an item as purchased
    Given a wishlist with an unpurchased item
    When the other user marks the item as purchased
    Then the item is marked purchased by the other user

  Scenario: Owner cannot mark their own list's item as purchased
    Given a wishlist with an unpurchased item
    When the owner tries to mark the item as purchased
    Then the item is still unpurchased

  Scenario: Purchaser can toggle an item back to not-purchased
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When the other user marks the item as purchased
    Then the item is still unpurchased

  Scenario: Already-purchased item cannot be re-purchased by a third user
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When a third user tries to mark the item as purchased
    Then the item is marked purchased by the other user

  Scenario: Purchase status is visible to non-owners
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When a third user views the wishlist page
    Then the page shows "Purchased by"

  Scenario: Purchase status is hidden from the list owner
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When the owner views the wishlist page
    Then the page does not show "Purchased by"
