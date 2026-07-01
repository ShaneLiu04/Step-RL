"""Streamlit-based feedback dashboard for human review."""

import streamlit as st
from pathlib import Path
import json


class FeedbackDashboard:
    """Streamlit dashboard for reviewing and annotating trajectories."""

    def __init__(self, store_dir: str = "./data/trajectories"):
        self.store_dir = Path(store_dir)
        self.pending_dir = self.store_dir / "pending"

    def render(self):
        st.title("Step-RL Trajectory Review Dashboard")

        pending_files = sorted(self.pending_dir.glob("*.json"))
        st.write(f"Pending review: {len(pending_files)} trajectories")

        if not pending_files:
            st.success("All trajectories reviewed!")
            return

        # Show first pending trajectory
        traj_file = pending_files[0]
        with open(traj_file, "r", encoding="utf-8") as f:
            traj = json.load(f)

        st.subheader(f"Trajectory: {traj.get('trajectory_id', 'unknown')}")
        st.json(traj)

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("👍 Approve", key="approve"):
                self._approve(traj_file)
        with col2:
            if st.button("👎 Reject", key="reject"):
                self._reject(traj_file)
        with col3:
            if st.button("⏭️ Skip", key="skip"):
                pass

    def _approve(self, file_path: Path):
        approved_dir = self.store_dir / "approved"
        approved_dir.mkdir(exist_ok=True)
        file_path.rename(approved_dir / file_path.name)

    def _reject(self, file_path: Path):
        rejected_dir = self.store_dir / "rejected"
        rejected_dir.mkdir(exist_ok=True)
        file_path.rename(rejected_dir / file_path.name)
