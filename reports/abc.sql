SELECT *
FROM customers AS C
INNER JOIN orders AS O ON
C.customer_id = O.customer_id
INNER JOIN order_items AS OI ON
OI.order_id = O.order_id
INNER JOIN stores AS S ON
S.store_id = O.store_id
