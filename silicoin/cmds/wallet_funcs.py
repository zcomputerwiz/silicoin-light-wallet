import asyncio
import pathlib
import sys
import time
from datetime import datetime
from decimal import Decimal
from typing import Callable, List, Optional, Tuple, Dict

import aiohttp

from silicoin.cmds.units import units
from silicoin.rpc.wallet_rpc_client import WalletRpcClient
from silicoin.server.start_wallet import SERVICE_NAME
from silicoin.util.bech32m import encode_puzzle_hash
from silicoin.util.byte_types import hexstr_to_bytes
from silicoin.util.config import load_config
from silicoin.util.default_root import DEFAULT_ROOT_PATH
from silicoin.util.ints import uint16, uint32, uint64
from silicoin.wallet.trading.offer import Offer
from silicoin.wallet.trading.trade_status import TradeStatus
from silicoin.wallet.transaction_record import TransactionRecord
from silicoin.wallet.util.wallet_types import WalletType


def print_transaction(tx: TransactionRecord, verbose: bool, name) -> None:
    if verbose:
        print(tx)
    else:
        silicoin_amount = Decimal(int(tx.amount)) / units["silicoin"]
        to_address = encode_puzzle_hash(tx.to_puzzle_hash, name)
        print(f"Transaction {tx.name}")
        print(f"Status: {'Confirmed' if tx.confirmed else ('In mempool' if tx.is_in_mempool() else 'Pending')}")
        print(f"Amount {'sent' if tx.sent else 'received'}: {silicoin_amount} {name}")
        print(f"To address: {to_address}")
        print("Created at:", datetime.fromtimestamp(tx.created_at_time).strftime("%Y-%m-%d %H:%M:%S"))
        memos_dict = tx.get_memos()
        if len(memos_dict) > 0:
            print("Memos:")
            for coin_id, memos in memos_dict.items():
                print(coin_id)
                for memo in memos:
                    try:
                        decoded = memo.decode("utf-8")
                        print(f"   - {decoded}")
                    except Exception:
                        print(f"   - {memo.hex()}")
        print("")


async def get_transaction(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    transaction_id = hexstr_to_bytes(args["tx_id"])
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    name = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    tx: TransactionRecord = await wallet_client.get_transaction(wallet_id, transaction_id=transaction_id)
    print_transaction(tx, verbose=(args["verbose"] > 0), name=name)


async def get_transactions(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    paginate = args["paginate"]
    if paginate is None:
        paginate = sys.stdout.isatty()
    txs: List[TransactionRecord] = await wallet_client.get_transactions(wallet_id)
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    name = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    if len(txs) == 0:
        print("There are no transactions to this address")

    offset = args["offset"]
    num_per_screen = 5 if paginate else len(txs)
    for i in range(offset, len(txs), num_per_screen):
        for j in range(0, num_per_screen):
            if i + j >= len(txs):
                break
            print_transaction(txs[i + j], verbose=(args["verbose"] > 0), name=name)
        if i + num_per_screen >= len(txs):
            return None
        print("Press q to quit, or c to continue")
        while True:
            entered_key = sys.stdin.read(1)
            if entered_key == "q":
                return None
            elif entered_key == "c":
                break


def check_unusual_transaction(amount: Decimal, fee: Decimal):
    return fee >= amount


async def send(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:

    wallet_id = args["id"]
    amount = Decimal(args["amount"])
    fee = Decimal(args["fee"])
    address = args["address"]
    override = args["override"]
    memo = args["memo"]
    if memo is None:
        memos = None
    else:
        memos = [memo]

    if not override and check_unusual_transaction(amount, fee):
        print(
            f"A transaction of amount {amount} and fee {fee} is unusual.\n"
            f"Pass in --override if you are sure you mean to do this."
        )
        return

    summaries_response = await wallet_client.get_wallets()
    final_amount: Optional[uint64] = None
    final_fee = uint64(int(fee * units["silicoin"]))
    for summary in summaries_response:
        if int(wallet_id) == int(summary["id"]):
            typ: WalletType = WalletType(int(summary["type"]))
            if typ == WalletType.STANDARD_WALLET:
                final_amount = uint64(int(amount * units["silicoin"]))
                print("Submitting transaction...")
                res = await wallet_client.send_transaction(wallet_id, final_amount, address, final_fee, memos)
                break
            elif typ == WalletType.COLOURED_COIN:
                final_amount = uint64(int(amount * units["colouredcoin"]))
                print("Submitting transaction...")
                res = await wallet_client.cat_spend(wallet_id, final_amount, address, final_fee, memos)
                break
            else:
                print("Only standard wallet and CAT wallets are supported")
                return
    if final_amount is None:
        print(f"Wallet id: {wallet_id} not found.")
        return
    tx_id = res.name
    start = time.time()
    while time.time() - start < 10:
        await asyncio.sleep(0.1)
        tx = await wallet_client.get_transaction(wallet_id, tx_id)
        if len(tx.sent_to) > 0:
            print(f"Transaction submitted to nodes: {tx.sent_to}")
            print(f"Do silicoin wallet get_transaction -f {fingerprint} -tx 0x{tx_id} to get status")
            return None

    print("Transaction not yet submitted to nodes")
    print(f"Do 'silicoin wallet get_transaction -f {fingerprint} -tx 0x{tx_id}' to get status")


async def get_address(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    res = await wallet_client.get_next_address(wallet_id, False)
    print(res)


async def delete_unconfirmed_transactions(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    wallet_id = args["id"]
    await wallet_client.delete_unconfirmed_transactions(wallet_id)
    print(f"Successfully deleted all unconfirmed transactions for wallet id {wallet_id} on key {fingerprint}")


async def add_token(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    asset_id = args["asset_id"]
    token_name = args["token_name"]
    try:
        asset_id_bytes: bytes = hexstr_to_bytes(asset_id)
        response = await wallet_client.create_wallet_for_existing_cat(asset_id_bytes)
        wallet_id = response["wallet_id"]
        await wallet_client.set_cat_name(wallet_id, token_name)
        print(f"Successfully added {token_name} with wallet id {wallet_id} on key {fingerprint}")
    except ValueError as e:
        if "fromhex()" in str(e):
            print(f"{asset_id} is not a valid Asset ID")
        else:
            raise e


async def make_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    offers: List[str] = args["offers"]
    requests: List[str] = args["requests"]
    filepath: str = args["filepath"]
    fee: int = int(Decimal(args["fee"]) * units["silicoin"])

    if [] in [offers, requests]:
        print("Not creating offer: Must be offering and requesting at least one asset")
    else:
        offer_dict: Dict[uint32, int] = {}
        printable_dict: Dict[str, Tuple[str, int, int]] = {}  # Dict[asset_name, Tuple[amount, unit, multiplier]]
        for item in [*offers, *requests]:
            wallet_id, amount = tuple(item.split(":")[0:2])
            if int(wallet_id) == 1:
                name: str = "SIT"
                unit: int = units["silicoin"]
            else:
                name = await wallet_client.get_cat_name(wallet_id)
                unit = units["colouredcoin"]
            multiplier: int = -1 if item in offers else 1
            printable_dict[name] = (amount, unit, multiplier)
            if uint32(int(wallet_id)) in offer_dict:
                print("Not creating offer: Cannot offer and request the same asset in a trade")
                break
            else:
                offer_dict[uint32(int(wallet_id))] = int(Decimal(amount) * unit) * multiplier
        else:
            print("Creating Offer")
            print("--------------")
            print()
            print("OFFERING:")
            for name, info in printable_dict.items():
                amount, unit, multiplier = info
                if multiplier < 0:
                    print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")
            print("REQUESTING:")
            for name, info in printable_dict.items():
                amount, unit, multiplier = info
                if multiplier > 0:
                    print(f"  - {amount} {name} ({int(Decimal(amount) * unit)} mojos)")

            confirmation = input("Confirm (y/n): ")
            if confirmation not in ["y", "yes"]:
                print("Not creating offer...")
            else:
                offer, trade_record = await wallet_client.create_offer_for_ids(offer_dict, fee=fee)
                if offer is not None:
                    with open(pathlib.Path(filepath), "w") as file:
                        file.write(bytes(offer).hex())
                    print(f"Created offer with ID {trade_record.trade_id}")
                    print(f"Use silicoin wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view status")
                else:
                    print("Error creating offer")


def timestamp_to_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


async def print_offer_summary(wallet_client: WalletRpcClient, sum_dict: dict):
    for asset_id, amount in sum_dict.items():
        if asset_id == "sit":
            wid: str = "1"
            name: str = "SIT"
            unit: int = units["silicoin"]
        else:
            result = await wallet_client.cat_asset_id_to_name(bytes.fromhex(asset_id))
            wid = "Unknown"
            name = asset_id
            unit = units["colouredcoin"]
            if result is not None:
                wid = str(result[0])
                name = result[1]
        print(f"    - {name} (Wallet ID: {wid}): {Decimal(int(amount)) / unit} ({int(Decimal(amount))} mojos)")


async def print_trade_record(record, wallet_client: WalletRpcClient, summaries: bool = False) -> None:
    print()
    print(f"Record with id: {record.trade_id}")
    print("---------------")
    print(f"Created at: {timestamp_to_time(record.created_at_time)}")
    print(f"Confirmed at: {record.confirmed_at_index}")
    print(f"Accepted at: {timestamp_to_time(record.accepted_at_time) if record.accepted_at_time else 'N/A'}")
    print(f"Status: {TradeStatus(record.status).name}")
    if summaries:
        print("Summary:")
        offer = Offer.from_bytes(record.offer)
        offered, requested = offer.summary()
        print("  OFFERED:")
        await print_offer_summary(wallet_client, offered)
        print("  REQUESTED:")
        await print_offer_summary(wallet_client, requested)
        print("Pending Balances:")
        await print_offer_summary(wallet_client, offer.get_pending_amounts())
        print(f"Fees: {Decimal(offer.bundle.fees()) / units['silicoin']}")
    print("---------------")


async def get_offers(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    id, filepath, all, summaries = tuple(list(args.values())[0:4])
    file_contents: bool = (filepath is not None) or summaries
    if id is None:
        records = await wallet_client.get_all_offers(file_contents)
    else:
        records = [await wallet_client.get_offer(hexstr_to_bytes(id), file_contents)]
        if filepath is not None:
            with open(pathlib.Path(filepath), "w") as file:
                file.write(records[0].offer.hex())
                file.close()

    for record in records:
        if "PENDING" in TradeStatus(record.status).name or all or id is not None:
            await print_trade_record(record, wallet_client, summaries=summaries)


async def take_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    if "." in args["file"]:
        filepath = pathlib.Path(args["file"])
        with open(filepath, "r") as file:
            offer_hex: str = file.read()
            file.close()
    else:
        offer_hex = args["file"]

    examine_only: bool = args["examine_only"]
    fee: int = int(Decimal(args["fee"]) * units["silicoin"])

    try:
        offer = Offer.from_bytes(hexstr_to_bytes(offer_hex))
    except ValueError:
        print("Please enter a valid offer file or hex blob")
        return

    offered, requested = offer.summary()
    print("Summary:")
    print("  OFFERED:")
    await print_offer_summary(wallet_client, offered)
    print("  REQUESTED:")
    await print_offer_summary(wallet_client, requested)
    print(f"Fees: {Decimal(offer.bundle.fees()) / units['silicoin']}")

    if not examine_only:
        confirmation = input("Would you like to take this offer? (y/n): ")
        if confirmation in ["y", "yes"]:
            trade_record = await wallet_client.take_offer(offer, fee=fee)
            print(f"Accepted offer with ID {trade_record.trade_id}")
            print(f"Use silicoin wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view its status")


async def cancel_offer(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    id = hexstr_to_bytes(args["id"])
    secure: bool = not args["insecure"]
    fee: int = int(Decimal(args["fee"]) * units["silicoin"])

    trade_record = await wallet_client.get_offer(id, file_contents=True)
    await print_trade_record(trade_record, wallet_client, summaries=True)

    confirmation = input(f"Are you sure you wish to cancel offer with ID: {trade_record.trade_id}? (y/n): ")
    if confirmation in ["y", "yes"]:
        await wallet_client.cancel_offer(id, secure=secure, fee=fee)
        print(f"Cancelled offer with ID {trade_record.trade_id}")
        if secure:
            print(f"Use silicoin wallet get_offers --id {trade_record.trade_id} -f {fingerprint} to view cancel status")


def wallet_coin_unit(typ: WalletType, address_prefix: str) -> Tuple[str, int]:
    if typ == WalletType.COLOURED_COIN:
        return "", units["colouredcoin"]
    if typ in [WalletType.STANDARD_WALLET, WalletType.POOLING_WALLET, WalletType.MULTI_SIG, WalletType.RATE_LIMITED]:
        return address_prefix, units["silicoin"]
    return "", units["mojo"]


def print_balance(amount: int, scale: int, address_prefix: str) -> str:
    ret = f"{amount/scale} {address_prefix} "
    if scale > 1:
        ret += f"({amount} mojo)"
    return ret


async def print_balances(args: dict, wallet_client: WalletRpcClient, fingerprint: int) -> None:
    summaries_response = await wallet_client.get_wallets()
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    address_prefix = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]

    print(f"Wallet height: {await wallet_client.get_height_info()}")
    if await wallet_client.get_sync_status():
        print("Sync status: Syncing...")
    else:
        print(f"Sync status: {'Synced' if (await wallet_client.get_synced()) else 'Not synced'}")
    print(f"Balances, fingerprint: {fingerprint}")
    for summary in summaries_response:
        wallet_id = summary["id"]
        balances = await wallet_client.get_wallet_balance(wallet_id)
        typ = WalletType(int(summary["type"]))
        address_prefix, scale = wallet_coin_unit(typ, address_prefix)
        if typ == WalletType.COLOURED_COIN:
            asset_id = await wallet_client.get_cat_colour(wallet_id)
            asset_id_str = f"(Asset ID: {asset_id.hex()})"
        else:
            asset_id_str = ""
        print(f"Wallet ID {wallet_id} type {typ.name} {summary['name']} {asset_id_str}")
        print(f"   -Total Balance: {print_balance(balances['confirmed_wallet_balance'], scale, address_prefix)}")
        print(
            f"   -Pending Total Balance: {print_balance(balances['unconfirmed_wallet_balance'], scale, address_prefix)}"
        )
        print(f"   -Spendable: {print_balance(balances['spendable_balance'], scale, address_prefix)}")


async def get_wallet(wallet_client: WalletRpcClient, fingerprint: int = None) -> Optional[Tuple[WalletRpcClient, int]]:
    if fingerprint is not None:
        fingerprints = [fingerprint]
    else:
        fingerprints = await wallet_client.get_public_keys()
    if len(fingerprints) == 0:
        print("No keys loaded. Run 'silicoin keys generate' or import a key")
        return None
    if len(fingerprints) == 1:
        fingerprint = fingerprints[0]
    if fingerprint is not None:
        log_in_response = await wallet_client.log_in(fingerprint)
    else:
        print("Choose wallet key:")
        for i, fp in enumerate(fingerprints):
            print(f"{i+1}) {fp}")
        val = None
        while val is None:
            val = input("Enter a number to pick or q to quit: ")
            if val == "q":
                return None
            if not val.isdigit():
                val = None
            else:
                index = int(val) - 1
                if index >= len(fingerprints):
                    print("Invalid value")
                    val = None
                    continue
                else:
                    fingerprint = fingerprints[index]
        assert fingerprint is not None
        log_in_response = await wallet_client.log_in(fingerprint)

    if log_in_response["success"] is False:
        if log_in_response["error"] == "not_initialized":
            use_cloud = True
            if "backup_path" in log_in_response:
                path = log_in_response["backup_path"]
                print(f"Backup file from backup.sitnetwork.net downloaded and written to: {path}")
                val = input("Do you want to use this file to restore from backup? (Y/N) ")
                if val.lower() == "y":
                    log_in_response = await wallet_client.log_in_and_restore(fingerprint, path)
                else:
                    use_cloud = False

            if "backup_path" not in log_in_response or use_cloud is False:
                if use_cloud is True:
                    val = input(
                        "No online backup file found,\n Press S to skip restore from backup"
                        "\n Press F to use your own backup file: "
                    )
                else:
                    val = input(
                        "Cloud backup declined,\n Press S to skip restore from backup"
                        "\n Press F to use your own backup file: "
                    )

                if val.lower() == "s":
                    log_in_response = await wallet_client.log_in_and_skip(fingerprint)
                elif val.lower() == "f":
                    val = input("Please provide the full path to your backup file: ")
                    log_in_response = await wallet_client.log_in_and_restore(fingerprint, val)

    if "success" not in log_in_response or log_in_response["success"] is False:
        if "error" in log_in_response:
            error = log_in_response["error"]
            print(f"Error: {log_in_response[error]}")
        return None
    return wallet_client, fingerprint


async def execute_with_wallet(
    wallet_rpc_port: Optional[int], fingerprint: int, extra_params: Dict, function: Callable
) -> None:
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if wallet_rpc_port is None:
            wallet_rpc_port = config["wallet"]["rpc_port"]
        wallet_client = await WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
        wallet_client_f = await get_wallet(wallet_client, fingerprint=fingerprint)
        if wallet_client_f is None:
            wallet_client.close()
            await wallet_client.await_closed()
            return None
        wallet_client, fingerprint = wallet_client_f
        await function(extra_params, wallet_client, fingerprint)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        if isinstance(e, aiohttp.ClientConnectorError):
            print(
                f"Connection error. Check if the wallet is running at {wallet_rpc_port}. "
                "You can run the wallet via:\n\tsilicoin start wallet"
            )
        else:
            print(f"Exception from 'wallet' {e}")
    wallet_client.close()
    await wallet_client.await_closed()
