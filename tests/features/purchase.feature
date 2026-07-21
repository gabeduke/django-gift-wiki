Feature: Wishlist item purchase rules
  Anyone on the family can mark a wishlist item as purchased except the
  list's owner or managers (no spoilers). A purchaser may toggle their
  own purchase back off. Once an item is purchased, it is shown as
  "Purchased" anonymously by default; a reveal control lets curious
  viewers see who purchased it. List owners/managers see no purchase
  information at all.

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

  Scenario: Purchased status is anonymous by default for non-owners
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When a third user views the wishlist page
    Then the page shows "Purchased" anonymously
    And the page hides the purchaser name by default
    And the page has a reveal purchaser control

  Scenario: Purchase information is hidden from the list owner
    Given a wishlist with an unpurchased item
    And the other user has already purchased the item
    When the owner views the wishlist page
    Then the page does not show purchase information
