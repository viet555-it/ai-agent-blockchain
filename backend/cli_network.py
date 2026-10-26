import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.network.config import DEFAULT_NETWORKS
from backend.network.network_manager import NetworkManager
from backend.services.blockchain_service import BlockchainService



def cmd_networks(args, manager: NetworkManager):
    print("\n--- Registered Networks ---")
    for net in manager.list_networks():
        active_tag = " (ACTIVE)" if net["is_active"] else ""
        print(f"[{net['chain_id']}] {net['name']}{active_tag}")
        print(f"    Currency: {net['native_currency']} | Testnet: {net['is_testnet']} | RPC Endpoints: {net['rpc_count']}")
    print()


def cmd_health(args, manager: NetworkManager):
    chain_id = args.chain_id or manager.active_chain_id
    config = manager.get_network_config(chain_id)
    print(f"\nChecking health for {config.name} (Chain {chain_id})...")
    for url in config.all_rpc_urls():
        health = manager.check_rpc_health(url, chain_id)
        status_symbol = "[OK]" if health.is_healthy else "[FAIL]"
        print(f" {status_symbol} {url}")
        print(f"      Latency: {health.latency_ms:.1f}ms | Status: {health.to_dict()['status']}")
        if health.is_healthy:
            print(f"      Block: #{health.block_number} | Gas Price: {health.gas_price_wei / 1e9:.2f} gwei")
        else:
            print(f"      Error: {health.error}")
    print()


def cmd_balance(args, service: BlockchainService):
    addr = args.address
    print(f"\n--- Balances for {addr} on Chain {service.chain_id} ---")
    native = service.get_native_balance(addr)
    print(f" Native Balance: {native['balance']} {native['symbol']}")

    if args.token:
        token = service.get_token_balance(args.token, addr)
        print(f" Token Balance:  {token['balance']} {token['symbol']} ({args.token})")
    print()


def cmd_simulate(args, service: BlockchainService):
    print(f"\nSimulating transfer on Chain {service.chain_id}...")
    res = service.simulate_transfer(
        sender=args.sender,
        recipient=args.recipient,
        amount_token=args.amount,
        token_address=args.token,
        spender=args.spender,
    )
    status = "SUCCESS (VALID)" if res["isValid"] else "REVERTED / INVALID"
    print(f" Simulation Result: {status}")
    print(f" Reason:            {res['reason']}")
    print(f" Sender:            {res['sender']}")
    print(f" Recipient:         {res['recipient']}")
    print(f" Amount:            {res['amount']} tokens")
    print()


def main():
    parser = argparse.ArgumentParser(description="Blockchain Service & Network CLI")
    parser.add_argument("--chain-id", type=int, default=31337, help="Target chain ID (default: 31337)")
    subparsers = parser.add_subparsers(dest="command")

    # Command: networks
    subparsers.add_parser("networks", help="List registered networks")

    # Command: health
    subparsers.add_parser("health", help="Check RPC health and latencies")

    # Command: balance
    p_bal = subparsers.add_parser("balance", help="Check native or token balance")
    p_bal.add_argument("address", help="Wallet address to check")
    p_bal.add_argument("--token", help="Optional ERC-20 token address")

    # Command: simulate
    p_sim = subparsers.add_parser("simulate", help="Simulate a token transfer via eth_call")
    p_sim.add_argument("--sender", required=True, help="Sender address")
    p_sim.add_argument("--recipient", required=True, help="Recipient address")
    p_sim.add_argument("--amount", required=True, help="Token amount decimal string")
    p_sim.add_argument("--token", help="Token contract address (default: deployed AgentToken)")
    p_sim.add_argument("--spender", help="Spender address if simulating transferFrom")

    args = parser.parse_args()

    manager = NetworkManager()
    if args.chain_id in DEFAULT_NETWORKS:
        manager.set_active_chain_id(args.chain_id)

    if args.command == "networks":
        cmd_networks(args, manager)
    elif args.command == "health":
        cmd_health(args, manager)
    elif args.command in ("balance", "simulate"):
        try:
            service = BlockchainService(chain_id=args.chain_id, network_manager=manager)
            if args.command == "balance":
                cmd_balance(args, service)
            elif args.command == "simulate":
                cmd_simulate(args, service)
        except Exception as exc:
            print(f"[-] Error connecting to chain {args.chain_id}: {exc}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
