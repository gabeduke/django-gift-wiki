var wishlistId = window.location.pathname.split('/')[2];
// JavaScript code to handle adding new items to a wishlist
document.getElementById('add-item-btn').addEventListener('click', function () {
    var itemName = document.getElementById('item_name').value;

    // Add other fields as needed

    // AJAX request to Django
    fetch(`/wishlist/${wishlistId}/add_item_ajax/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') // Function to get CSRF token
        },
        body: JSON.stringify({name: itemName /*, other fields */})
    })
        .then(response => response.json())
        .then(data => {
            // Update the page with the new item
            // You can append the new item to 'wishlist-items' div
        });
});

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

