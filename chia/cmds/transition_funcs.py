from typing import Dict, Optional
from pathlib import Path
import sys

import asyncio
import zstd

from chia.util.config import load_config, save_config
from chia.util.path import mkdir, path_from_root
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.sized_bytes import bytes32


# if either the input database or output database file is specified, the
# configuration file will not be updated to use the new database. Only when using
# the currently configured db file, and writing to the default output file will
# the configuration file also be updated
def transition_func(root_path: Path, in_db_path: Optional[Path] = None, out_db_path: Optional[Path] = None):

    update_config: bool = in_db_path is None and out_db_path is None

    config: Dict
    selected_network: str
    db_pattern: str
    if in_db_path is None or out_db_path is None:
        config = load_config(root_path, "config.yaml")["full_node"]
        selected_network = config["selected_network"]
        db_pattern = config["database_path"]

    db_path_replaced: str
    if in_db_path is None:
        db_path_replaced = db_pattern.replace("CHALLENGE", selected_network)
        in_db_path = path_from_root(root_path, db_path_replaced)

    if out_db_path is None:
        db_path_replaced = db_pattern.replace("CHALLENGE", selected_network).replace("_v1_", "_v2_")
        out_db_path = path_from_root(root_path, db_path_replaced)
        mkdir(out_db_path.parent)

    asyncio.run(convert_v1_to_v2(in_db_path, out_db_path))

    if update_config:
        print("updating config.yaml")
        config = load_config(root_path, "config.yaml")
        new_db_path = db_pattern.replace("_v1_", "_v2_")
        config["full_node"]["database_path"] = new_db_path
        print(f"database_path: {new_db_path}")
        save_config(root_path, "config.yaml", config)


async def convert_v1_to_v2(in_path: Path, out_path: Path):
    import aiosqlite
    from chia.util.db_wrapper import DBWrapper

    if out_path.exists():
        print(f"output file already exists. {out_path}")
        return

    print(f"opening file for reading: {in_path}")
    async with aiosqlite.connect(in_path) as in_db:
        try:
            async with in_db.execute("SELECT * from database_version") as cursor:
                row = await cursor.fetchone()
                if row is not None and row[0] != 1:
                    print(f"blockchain database already version {row[0]}\nDone")
                    return
        except aiosqlite.OperationalError:
            pass

        store_v1 = await BlockStore.create(DBWrapper(in_db, db_version=1))

        print(f"opening file for writing: {out_path}")
        async with aiosqlite.connect(out_path) as out_db:
            print("initializing v2 version")
            await out_db.execute("CREATE TABLE database_version(version int)")
            await out_db.execute("INSERT INTO database_version VALUES(?)", (2,))

            print("initializing v2 block store")
            await BlockStore.create(DBWrapper(out_db, db_version=2))

            peak_hash, peak_height = await store_v1.get_peak()
            print(f"peak: {peak_hash.hex()} height: {peak_height}")

            await out_db.execute("INSERT INTO current_peak VALUES(?, ?)", (0, peak_hash))

            print("converting full_blocks")
            height = peak_height + 1
            hh = peak_hash

            async with in_db.execute(
                "SELECT header_hash, prev_hash, block, sub_epoch_summary FROM block_records ORDER BY height DESC"
            ) as cursor:
                async for row in cursor:

                    header_hash = bytes.fromhex(row[0])
                    if header_hash != hh:
                        continue

                    prev_hash = bytes.fromhex(row[1])
                    block_record = row[2]
                    ses = row[3]

                    async with in_db.execute(
                        "SELECT height, is_fully_compactified, block FROM full_blocks WHERE header_hash=?", (hh.hex(),)
                    ) as cursor_2:
                        row_2 = await cursor_2.fetchone()
                        if row_2 is None:
                            print(f"ERROR: could not find block {hh.hex()}")
                            return
                        assert row_2[0] == height - 1
                        height = row_2[0]
                        is_fully_compactified = row_2[1]
                        block_bytes = row_2[2]

                    await out_db.execute(
                        "INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            hh,
                            prev_hash,
                            height,
                            ses,
                            is_fully_compactified,
                            1,  # in_main_chain
                            zstd.compress(block_bytes),
                            block_record,
                        ),
                    )
                    await out_db.commit()
                    hh = prev_hash
                    if (height % 1000) == 0:
                        print(f"\r{height: 10d} {(peak_height-height)*100/peak_height:.2f}%  ", end="")
                        sys.stdout.flush()
            print("")

            print("converting sub_epoch_segments_v3")
            async with in_db.execute("SELECT ses_block_hash, challenge_segments FROM sub_epoch_segments_v3") as cursor:
                count = 0
                async for row in cursor:
                    block_hash = bytes32.fromhex(row[0])
                    ses = row[1]
                    await out_db.execute("INSERT INTO sub_epoch_segments_v3 VALUES (?, ?)", (block_hash, ses))
                    await out_db.commit()
                    count += 1
                    if (count % 100) == 0:
                        print(f"\r{count}  ", end="")
                        sys.stdout.flush()
            print("")

            print("initializing v2 coin store")
            await CoinStore.create(DBWrapper(out_db, db_version=2))
            print("converting coin_store")

            async with in_db.execute(
                "SELECT coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp "
                "FROM coin_record WHERE spent_index <= ? AND confirmed_index <= ?",
                (
                    peak_height,
                    peak_height,
                ),
            ) as cursor:
                count = 0
                async for row in cursor:
                    await out_db.execute(
                        "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            bytes.fromhex(row[0]),
                            row[1],
                            row[2],
                            row[3],
                            bytes.fromhex(row[4]),
                            bytes.fromhex(row[5]),
                            row[6],
                            row[7],
                        ),
                    )
                    await out_db.commit()
                    count += 1
                    if (count % 1000) == 0:
                        print(f"\r{count}  ", end="")
                        sys.stdout.flush()
            print("")
