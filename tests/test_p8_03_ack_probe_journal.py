"""Fail-closed reconstruction of every v2 motion request."""

import copy
import unittest

from scripts.p8_03_timing_score import _motion_request_accounting


def request_rows(*, late=False):
    deadline = 1_000_000_000
    wake = deadline + 1_000
    start = {"kind": "motion_request_start", "timestamp_ns": wake,
             "period_index": 0, "scored_slot": None, "phase": "prearm",
             "scheduled_deadline_ns": deadline,
             "next_deadline_ns": deadline + 20_000_000,
             "worker_wake_ns": wake, "thread_id": 17,
             "previous_slot_completion_ns": None,
             "state_queue_depth": 0, "pose_queue_depth": 0,
             "request_id": 2, "outstanding_before": 0}
    ack = deadline + (21_000_000 if late else 1_000_000)
    end = {**start, "kind": "motion_request_end", "timestamp_ns": ack + 100,
           "lock_wait_start_ns": wake + 100,
           "command_lock_acquired_ns": wake + 200,
           "pre_send_ns": wake + 300, "timeout_s": 2.0,
           "socket_write_start_ns": wake + 400,
           "socket_write_end_ns": wake + 500,
           "flush_end_ns": wake + 600,
           "response_wait_start_ns": wake + 700,
           "first_response_byte_ns": ack - 200,
           "parse_complete_ns": ack - 100,
           "ack_ns": ack, "first_response_byte_observable": True,
           "status": "late_ack" if late else "acknowledged",
           "failure_reason": "motion_slot_missed:ACK_after_next_deadline" if late else None}
    attempt = {**end, "kind": "motion_attempt"}
    refresh = {"kind": "motion_refresh", "phase": "prearm", "period_index": 0,
               "scored_slot": None, "scheduled_deadline_ns": deadline,
               "move_ack_ns": ack}
    return [start, end], [attempt] if late else [attempt, refresh]


class MotionRequestJournalTests(unittest.TestCase):
    def test_acknowledged_request_has_matching_refresh(self):
        journal, timing = request_rows()
        self.assertEqual(_motion_request_accounting(journal, timing), [])

    def test_late_ack_has_complete_failure_row_without_refresh(self):
        journal, timing = request_rows(late=True)
        self.assertEqual(_motion_request_accounting(journal, timing),
                         ["motion_request_failed_attempt"])

    def test_missing_terminal_or_timing_row_fails(self):
        journal, timing = request_rows()
        self.assertIn("motion_request_terminal_or_attempt_missing",
                      _motion_request_accounting(journal[:1], timing))
        self.assertIn("motion_request_terminal_or_attempt_missing",
                      _motion_request_accounting(journal, timing[1:]))

    def test_mismatched_request_id_or_ack_trace_fails(self):
        journal, timing = request_rows()
        wrong_id = copy.deepcopy(journal)
        wrong_id[1]["request_id"] = 9
        self.assertIn("motion_request_row_invalid",
                      _motion_request_accounting(wrong_id, timing))
        wrong_ack = copy.deepcopy(journal)
        wrong_timing = copy.deepcopy(timing)
        wrong_ack[1]["first_response_byte_ns"] = None
        wrong_timing[0]["first_response_byte_ns"] = None
        self.assertIn("motion_request_ack_trace_invalid",
                      _motion_request_accounting(wrong_ack, wrong_timing))


if __name__ == "__main__":
    unittest.main()
