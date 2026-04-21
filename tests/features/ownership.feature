Feature: Wishlist ownership rules
  Wishlists belong to a single owner. Only the owner (or a designated
  manager) may edit items on a list, and only the owner may delete
  the list itself.

  Scenario: Owner can edit items on their wishlist
    Given a wishlist owned by the current user
    And an item on that wishlist
    When the owner edits the item name to "Edited by owner"
    Then the item name is "Edited by owner"

  Scenario: Non-owner cannot edit items
    Given a wishlist owned by the current user
    And an item on that wishlist
    When a non-owner edits the item name to "Edited by stranger"
    Then the item name is "Test Item"

  Scenario: Manager can edit items
    Given a wishlist owned by the current user
    And an item on that wishlist
    And the other user is a manager of the wishlist
    When the other user edits the item name to "Edited by manager"
    Then the item name is "Edited by manager"

  Scenario: Only the wishlist owner can delete a wishlist
    Given a wishlist owned by the current user
    When a non-owner attempts to delete the wishlist
    Then the wishlist still exists
    When the owner deletes the wishlist
    Then the wishlist no longer exists
