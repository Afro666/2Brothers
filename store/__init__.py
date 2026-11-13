"""MongoDB repository: the only package that talks to the database.

`db` holds the one connection; `orders` and `audit` hold the order workflow and the
audit log; `repository` holds the kitchen data (suppliers, own products, recipes,
menu plans).
"""
