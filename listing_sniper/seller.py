import logging
import os
import time
from web3 import Web3

logger = logging.getLogger(__name__)

SWAP_ROUTER_POLYGON = Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")
QUOTER_V2_POLYGON = Web3.to_checksum_address("0x61fFE014bA17989E743c5F6cB21bF9697530B21e")
USDC_POLYGON = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

ERC20_ABI = [
    {"inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]

QUOTER_ABI = [
    {
        "inputs": [{"components": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "fee", "type": "uint24"},
            {"name": "sqrtPriceLimitX96", "type": "uint160"},
        ], "name": "params", "type": "tuple"}],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "sqrtPriceX96After", "type": "uint160"},
            {"name": "initializedTicksCrossed", "type": "uint32"},
            {"name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

ROUTER_ABI = [
    {
        "inputs": [{"components": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "recipient", "type": "address"},
            {"name": "deadline", "type": "uint256"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMinimum", "type": "uint256"},
            {"name": "sqrtPriceLimitX96", "type": "uint160"},
        ], "name": "params", "type": "tuple"}],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]


def _connect() -> Web3:
    w3 = Web3(Web3.HTTPProvider(os.environ["POLYGON_HTTP_URL"]))
    if not w3.is_connected():
        raise ConnectionError("Polygon RPC not reachable")
    return w3


def get_current_value_usdc(token_address: str) -> float | None:
    """Quote how much USDC we'd receive for our entire token balance. Returns None on error."""
    try:
        w3 = _connect()
        wallet = Web3.to_checksum_address(os.environ["WALLET_ADDRESS"])
        token_addr = Web3.to_checksum_address(token_address)

        token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        balance = token.functions.balanceOf(wallet).call()
        if balance == 0:
            return 0.0

        quoter = w3.eth.contract(address=QUOTER_V2_POLYGON, abi=QUOTER_ABI)
        result = quoter.functions.quoteExactInputSingle({
            "tokenIn": token_addr,
            "tokenOut": USDC_POLYGON,
            "amountIn": balance,
            "fee": 3000,
            "sqrtPriceLimitX96": 0,
        }).call()

        return result[0] / 1_000_000  # USDC has 6 decimals

    except Exception as e:
        logger.debug(f"Quote failed for {token_address}: {e}")
        return None


def sell_token_for_usdc(token_address: str, min_usdc: float = 0.0) -> tuple[str | None, float]:
    """
    Sell entire token balance for USDC.
    Returns (tx_hash, usdc_received) or (None, 0.0) on failure.
    """
    try:
        w3 = _connect()
        wallet = Web3.to_checksum_address(os.environ["WALLET_ADDRESS"])
        pk = os.environ["PRIVATE_KEY"]
        token_addr = Web3.to_checksum_address(token_address)

        token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        balance = token.functions.balanceOf(wallet).call()
        if balance == 0:
            logger.warning(f"Zero balance for {token_address} — nothing to sell")
            return None, 0.0

        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(wallet)

        # Approve token for router
        approve_tx = token.functions.approve(SWAP_ROUTER_POLYGON, balance).build_transaction({
            "from": wallet, "nonce": nonce, "gas": 80_000, "gasPrice": gas_price,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, pk)
        w3.eth.wait_for_transaction_receipt(
            w3.eth.send_raw_transaction(signed_approve.raw_transaction), timeout=60
        )

        # Sell: token → USDC
        router = w3.eth.contract(address=SWAP_ROUTER_POLYGON, abi=ROUTER_ABI)
        deadline = int(time.time()) + 300
        min_out = max(1, int(min_usdc * 1_000_000 * 0.97))  # 3% slippage tolerance

        sell_tx = router.functions.exactInputSingle({
            "tokenIn": token_addr,
            "tokenOut": USDC_POLYGON,
            "fee": 3000,
            "recipient": wallet,
            "deadline": deadline,
            "amountIn": balance,
            "amountOutMinimum": min_out,
            "sqrtPriceLimitX96": 0,
        }).build_transaction({
            "from": wallet, "nonce": nonce + 1, "gas": 300_000, "gasPrice": gas_price,
        })
        signed_sell = w3.eth.account.sign_transaction(sell_tx, pk)
        receipt = w3.eth.wait_for_transaction_receipt(
            w3.eth.send_raw_transaction(signed_sell.raw_transaction), timeout=120
        )

        if receipt["status"] == 1:
            tx_hash = receipt["transactionHash"].hex()
            # Read actual USDC received from wallet balance change
            usdc = w3.eth.contract(address=USDC_POLYGON, abi=ERC20_ABI)
            usdc_after = usdc.functions.balanceOf(wallet).call() / 1_000_000
            logger.info(f"Sell successful: {tx_hash} — USDC balance now ${usdc_after:.2f}")
            return tx_hash, usdc_after
        else:
            logger.error(f"Sell tx reverted: {receipt['transactionHash'].hex()}")
            return None, 0.0

    except Exception as e:
        logger.error(f"Sell failed for {token_address}: {e}")
        return None, 0.0
