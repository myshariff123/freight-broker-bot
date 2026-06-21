import logging
import os
import time
from web3 import Web3

logger = logging.getLogger(__name__)

SWAP_ROUTER_POLYGON = Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")
USDC_POLYGON = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

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

ERC20_ABI = [
    {"inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def buy_on_polygon(token_address: str, usdc_usd: float = 50.0) -> str | None:
    """Buy token with USDC on Uniswap V3 Polygon. Returns tx hash or None."""
    try:
        w3 = Web3(Web3.HTTPProvider(os.environ["POLYGON_HTTP_URL"]))
        if not w3.is_connected():
            logger.error("Polygon RPC not connected")
            return None

        wallet = Web3.to_checksum_address(os.environ["WALLET_ADDRESS"])
        pk = os.environ["PRIVATE_KEY"]
        token_addr = Web3.to_checksum_address(token_address)
        usdc_amount = int(usdc_usd * 1_000_000)  # 6 decimals

        usdc = w3.eth.contract(address=USDC_POLYGON, abi=ERC20_ABI)
        balance = usdc.functions.balanceOf(wallet).call()
        if balance < usdc_amount:
            logger.warning(f"Insufficient USDC: have {balance/1e6:.2f}, need {usdc_usd}")
            return None

        gas_price = w3.eth.gas_price
        nonce = w3.eth.get_transaction_count(wallet)

        approve_tx = usdc.functions.approve(SWAP_ROUTER_POLYGON, usdc_amount).build_transaction({
            "from": wallet, "nonce": nonce, "gas": 80_000, "gasPrice": gas_price,
        })
        signed = w3.eth.account.sign_transaction(approve_tx, pk)
        w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), timeout=60)

        router = w3.eth.contract(address=SWAP_ROUTER_POLYGON, abi=ROUTER_ABI)
        deadline = int(time.time()) + 300
        swap_tx = router.functions.exactInputSingle({
            "tokenIn": USDC_POLYGON,
            "tokenOut": token_addr,
            "fee": 3000,
            "recipient": wallet,
            "deadline": deadline,
            "amountIn": usdc_amount,
            "amountOutMinimum": 1,
            "sqrtPriceLimitX96": 0,
        }).build_transaction({
            "from": wallet, "nonce": nonce + 1, "gas": 300_000, "gasPrice": gas_price,
        })
        signed_swap = w3.eth.account.sign_transaction(swap_tx, pk)
        receipt = w3.eth.wait_for_transaction_receipt(
            w3.eth.send_raw_transaction(signed_swap.raw_transaction), timeout=120
        )

        if receipt["status"] == 1:
            return receipt["transactionHash"].hex()
        logger.error(f"Swap reverted: {receipt['transactionHash'].hex()}")
        return None

    except Exception as e:
        logger.error(f"Buy failed for {token_address}: {e}")
        return None
