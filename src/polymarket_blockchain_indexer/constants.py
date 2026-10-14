"""Documented Polygon CTF exchange contracts and the OrderFilled event."""

CHAIN_ID = 137
CONTRACTS = {
    "ctf": "0xe111180000d2663c0091e4f400237545b87b996b",
    "neg-risk-ctf": "0xe2222d279d744050d28e00520010520000310f59",
}

# Keccak-256 of the canonical ABI signature below, checked against the local
# CTF Exchange V2 ABI. Keccak differs from Python's hashlib.sha3_256.
ORDER_FILLED_SIGNATURE = (
    "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
)
ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
