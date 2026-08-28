from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from ledgerlens.domain import AuditEvent
from ledgerlens.ingestion import CSVIngestor, load_mapping_profile
from ledgerlens.normalization import TransactionNormalizer
from ledgerlens.persistence import SQLiteLedgerLensStore


ROOT = Path(__file__).resolve().parents[2]


def _normalized_bank_batch():
    profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")
    batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_bank_statement.csv")
    normalized = TransactionNormalizer(profile).normalize(batch)
    return batch, normalized


class PersistenceSidecarTests(unittest.TestCase):
    def test_sqlite_store_initializes_wal_and_round_trips_ingested_batch(self):
        batch, normalized = _normalized_bank_batch()

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ledgerlens.db"
            store = SQLiteLedgerLensStore(db_path)
            store.initialize()
            run_id = store.create_run(client_id="acme", name="unit-test-run")
            store.save_source_file(batch.source_file)
            store.save_raw_transactions(batch.raw_transactions)
            store.save_normalized_transactions(run_id, normalized.transactions)

            self.assertEqual(store.journal_mode(), "wal")
            self.assertEqual(
                store.get_source_file(batch.source_file.id).file_hash,
                batch.source_file.file_hash,
            )
            self.assertEqual(len(store.list_raw_transactions(batch.source_file.id)), 6)

            rows = store.list_normalized_transactions(run_id)
            self.assertEqual(len(rows), 6)
            self.assertEqual(rows[0].amount, Decimal("1250.00"))
            self.assertEqual(rows[0].quality_flags, [])
            self.assertEqual(rows[3].quality_flags, ["missing_reference"])

    def test_sqlite_store_is_idempotent_for_duplicate_source_files_and_rows(self):
        batch, normalized = _normalized_bank_batch()

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteLedgerLensStore(Path(temp_dir) / "ledgerlens.db")
            store.initialize()
            run_id = store.create_run(client_id="acme", name="unit-test-run")

            store.save_source_file(batch.source_file)
            store.save_source_file(batch.source_file)
            store.save_raw_transactions(batch.raw_transactions)
            store.save_raw_transactions(batch.raw_transactions)
            store.save_normalized_transactions(run_id, normalized.transactions)
            store.save_normalized_transactions(run_id, normalized.transactions)

            self.assertEqual(len(store.list_source_files(client_id="acme")), 1)
            self.assertEqual(len(store.list_raw_transactions(batch.source_file.id)), 6)
            self.assertEqual(len(store.list_normalized_transactions(run_id)), 6)

    def test_sqlite_store_records_audit_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteLedgerLensStore(Path(temp_dir) / "ledgerlens.db")
            store.initialize()
            run_id = store.create_run(client_id="acme", name="audit-test")
            event = AuditEvent.create(
                run_id=run_id,
                entity_type="source_file",
                entity_id="src_example",
                event_type="source_file.ingested",
                actor_type="system",
                actor_id="ledgerlens.ingestion",
                after={"status": "ingested"},
                metadata={"row_count": 6},
            )

            store.record_audit_event(event)

            events = store.list_audit_events(run_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "source_file.ingested")
            self.assertEqual(events[0].metadata, {"row_count": 6})


if __name__ == "__main__":
    unittest.main()
