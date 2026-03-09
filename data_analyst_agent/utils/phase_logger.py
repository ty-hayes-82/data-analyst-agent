# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Phase-based logging utility for Data Analyst Agent.

Provides structured logging for each phase of the analysis pipeline:
- Phase 1: Data Ingestion & Validation
- Phase 2: Hierarchy Discovery & Planning
- Phase 3: Recursive Analysis
- Phase 4: Parallel Deep Analysis
- Phase 5: Synthesis & Structuring
- Phase 6: Alert Scoring & Persistence

Each phase logs:
- Start/end timestamps
- Input data summary
- Output data summary
- Errors and warnings
- Performance metrics
"""

import logging
import json
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from functools import wraps
import traceback
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


class PhaseLogger:
    """
    Centralized phase-based logger for Data Analyst workflow.
    
    Features:
    - Structured JSON logs per phase
    - Performance timing
    - Error tracking
    - Output file persistence
    - Console and file logging
    """
    
    def __init__(self, dimension_value: Optional[str] = None, log_dir: Optional[Path] = None):
        """
        Initialize phase logger.
        
        Args:
            dimension_value: Target dimension value being analyzed (e.g., "067" or "Line Haul")
            log_dir: Directory for log files (defaults to logs/ or from env)
        """
        # Check if phase logging is enabled
        self.enabled = os.getenv("PHASE_LOGGING_ENABLED", "true").lower() == "true"
        
        if not self.enabled:
            # Create a null logger that does nothing
            self.logger = logging.getLogger("data_analyst.disabled")
            self.logger.addHandler(logging.NullHandler())
            return
        
        self.dimension_value = dimension_value
        
        # Get log directory from environment or use default
        run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
        if run_dir:
            self.log_dir = Path(run_dir) / "logs"
        else:
            log_dir_env = os.getenv("PHASE_LOG_DIRECTORY", "logs")
            self.log_dir = log_dir or Path(__file__).parent.parent.parent / log_dir_env
        
        self.log_dir.mkdir(exist_ok=True, parents=True)
        
        # Get configuration from environment
        self.log_level = os.getenv("PHASE_LOG_LEVEL", "INFO").upper()
        self.save_summary = os.getenv("PHASE_LOG_SAVE_SUMMARY", "true").lower() == "true"
        self.console_format = os.getenv("PHASE_LOG_CONSOLE_FORMAT", "detailed")
        self.track_performance = os.getenv("PHASE_LOG_TRACK_PERFORMANCE", "true").lower() == "true"
        self.log_stack_traces = os.getenv("PHASE_LOG_STACK_TRACES", "true").lower() == "true"
        
        # Phase tracking
        self.phases = {}
        self.current_phase = None
        self.session_start = time.time()
        
        # Setup loggers
        self._setup_loggers()
    
    def _setup_loggers(self):
        """Configure logging handlers for console and file output."""
        # Main logger
        self.logger = logging.getLogger(f"data_analyst.{self.dimension_value or 'global'}")
        self.logger.setLevel(getattr(logging, self.log_level))
        self.logger.handlers.clear()
        
        # Console handler - structured output
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, self.log_level))
        
        # Format based on console_format setting
        if self.console_format == "simple":
            console_formatter = logging.Formatter('%(levelname)s: %(message)s')
        elif self.console_format == "json":
            console_formatter = logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
        else:  # detailed (default)
            console_formatter = logging.Formatter(
                '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler - detailed JSON logs
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
            log_file = self.log_dir / "execution.log"
        elif self.dimension_value:
            # Clean dimension value for filename
            safe_val = str(self.dimension_value).replace(" ", "_").replace("/", "-")
            log_file = self.log_dir / f"analysis_{safe_val}_{timestamp}.log"
        else:
            log_file = self.log_dir / f"data_analyst_{timestamp}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
        
        self.log_file = log_file
        self.logger.info(f"Phase logger initialized. Log file: {log_file}")
    
    def start_phase(self, phase_name: str, description: str = "", input_data: Optional[Dict[str, Any]] = None):
        """
        Mark the start of an analysis phase.
        
        Args:
            phase_name: Name of the phase
            description: Brief description of what this phase does
            input_data: Summary of input data (sanitized)
        """
        if not self.enabled:
            return
        
        phase_key = phase_name.lower().replace(" ", "_").replace(":", "")
        
        self.current_phase = phase_key
        self.phases[phase_key] = {
            "name": phase_name,
            "description": description,
            "start_time": time.time(),
            "start_timestamp": datetime.now().isoformat(),
            "input_summary": self._sanitize_data(input_data) if input_data else {},
            "status": "in_progress",
            "errors": [],
            "warnings": []
        }
        
        self.logger.info("="*80)
        self.logger.info(f"STARTING: {phase_name}")
        if description:
            self.logger.info(f"Description: {description}")
        if input_data and self.log_level == "DEBUG":
            self.logger.debug(f"Input Data: {json.dumps(self._sanitize_data(input_data), indent=2)}")
        self.logger.info("="*80)
    
    def end_phase(self, phase_name: str, output_data: Optional[Dict[str, Any]] = None, status: str = "completed"):
        """
        Mark the end of an analysis phase.
        """
        if not self.enabled:
            return
        
        phase_key = phase_name.lower().replace(" ", "_").replace(":", "")
        
        if phase_key not in self.phases:
            self.logger.warning(f"Phase {phase_name} was not started. Skipping end_phase.")
            return
        
        phase_info = self.phases[phase_key]
        phase_info["end_time"] = time.time()
        phase_info["end_timestamp"] = datetime.now().isoformat()
        phase_info["duration_seconds"] = phase_info["end_time"] - phase_info["start_time"]
        phase_info["output_summary"] = self._sanitize_data(output_data) if output_data else {}
        phase_info["status"] = status
        
        self.logger.info("="*80)
        self.logger.info(f"COMPLETED: {phase_name} [{status.upper()}]")
        self.logger.info(f"Duration: {phase_info['duration_seconds']:.2f}s")
        if output_data:
            self.logger.info(f"Output Data: {json.dumps(self._sanitize_data(output_data), indent=2)}")
        if phase_info["errors"]:
            self.logger.error(f"Errors ({len(phase_info['errors'])}): {json.dumps(phase_info['errors'], indent=2)}")
        if phase_info["warnings"]:
            self.logger.warning(f"Warnings ({len(phase_info['warnings'])}): {json.dumps(phase_info['warnings'], indent=2)}")
        self.logger.info("="*80)
        
        self.current_phase = None
    
    def log_metric(self, metric_name: str, value: Any):
        """Log a metric for the current phase."""
        if not self.enabled:
            return
        
        if not self.current_phase:
            self.logger.warning(f"No active phase. Logging metric to root: {metric_name}={value}")
            return
        
        if "metrics" not in self.phases[self.current_phase]:
            self.phases[self.current_phase]["metrics"] = {}
        
        self.phases[self.current_phase]["metrics"][metric_name] = value
        self.logger.info(f"Metric [{self.current_phase}]: {metric_name} = {value}")
    
    def log_error(self, error_message: str, exception: Optional[Exception] = None):
        """Log an error for the current phase."""
        if not self.enabled:
            return
        
        error_entry = {
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        
        if exception:
            error_entry["exception_type"] = type(exception).__name__
            error_entry["exception_str"] = str(exception)
            if self.log_stack_traces:
                error_entry["traceback"] = traceback.format_exc()
        
        if self.current_phase:
            self.phases[self.current_phase]["errors"].append(error_entry)
        
        self.logger.error(f"ERROR: {error_message}")
        if exception:
            self.logger.error(f"Exception: {type(exception).__name__}: {str(exception)}")
    
    def log_warning(self, warning_message: str):
        """Log a warning for the current phase."""
        if not self.enabled:
            return
        
        warning_entry = {
            "message": warning_message,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.current_phase:
            self.phases[self.current_phase]["warnings"].append(warning_entry)
        
        self.logger.warning(f"WARNING: {warning_message}")
    
    def save_phase_summary(self, output_dir: Optional[Path] = None):
        """Save complete phase execution summary to JSON file."""
        if not self.enabled or not self.save_summary:
            return None
        
        output_dir = output_dir or self.log_dir
        output_dir.mkdir(exist_ok=True)
        
        summary = {
            "dimension_value": self.dimension_value,
            "session_start": datetime.fromtimestamp(self.session_start).isoformat(),
            "session_end": datetime.now().isoformat(),
            "total_duration_seconds": time.time() - self.session_start,
            "phases": self.phases,
            "summary_statistics": self._calculate_summary_stats()
        }
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
            summary_file = output_dir / "phase_summary.json"
        elif self.dimension_value:
            safe_val = str(self.dimension_value).replace(" ", "_").replace("/", "-")
            summary_file = output_dir / f"summary_{safe_val}_{timestamp}.json"
        else:
            summary_file = output_dir / f"summary_global_{timestamp}.json"
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        self.logger.info(f"Phase summary saved to: {summary_file}")
        return summary_file
    
    def _calculate_summary_stats(self) -> Dict[str, Any]:
        """Calculate summary statistics across all phases."""
        total_duration = sum(p.get("duration_seconds", 0) for p in self.phases.values())
        total_errors = sum(len(p.get("errors", [])) for p in self.phases.values())
        total_warnings = sum(len(p.get("warnings", [])) for p in self.phases.values())
        
        completed = sum(1 for p in self.phases.values() if p.get("status") == "completed")
        failed = sum(1 for p in self.phases.values() if p.get("status") == "failed")
        skipped = sum(1 for p in self.phases.values() if p.get("status") == "skipped")
        
        return {
            "total_phases": len(self.phases),
            "phases_completed": completed,
            "phases_failed": failed,
            "phases_skipped": skipped,
            "total_duration_seconds": total_duration,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "success_rate": completed / len(self.phases) if self.phases else 0.0
        }
    
    def _sanitize_data(self, data: Any) -> Any:
        """Sanitize data for logging (truncate large objects)."""
        if data is None:
            return None
        
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 10:
                    sanitized[key] = {"type": "list", "length": len(value), "sample": value[:3]}
                elif isinstance(value, str) and len(value) > 200:
                    sanitized[key] = value[:200] + "... (truncated)"
                else:
                    sanitized[key] = self._sanitize_data(value)
            return sanitized
        
        elif isinstance(data, list):
            if len(data) > 10:
                return {"type": "list", "length": len(data), "sample": [self._sanitize_data(x) for x in data[:3]]}
            return [self._sanitize_data(x) for x in data]
        
        return data
    
    def log_workflow_transition(self, from_agent: str, to_agent: str, message: str = ""):
        """Log a workflow transition between agents."""
        if not self.enabled:
            return
        log_msg = f"Workflow Transition: {from_agent} -> {to_agent}"
        if message: log_msg += f" | {message}"
        self.logger.info(log_msg)
        if self.current_phase:
            if "transitions" not in self.phases[self.current_phase]:
                self.phases[self.current_phase]["transitions"] = []
            self.phases[self.current_phase]["transitions"].append({
                "from": from_agent, "to": to_agent, "message": message, "timestamp": datetime.now().isoformat()
            })
    
    def log_drill_down_decision(self, level: int, decision: str, reasoning: str, next_level: Optional[int] = None):
        """Log a drill-down decision."""
        if not self.enabled:
            return
        log_msg = f"Drill-Down Decision [Level {level}]: {decision}"
        if decision == "CONTINUE": log_msg += f" -> Level {next_level}"
        self.logger.info(log_msg)
        self.logger.info(f"  Reasoning: {reasoning}")
        if self.current_phase:
            if "drill_down_decisions" not in self.phases[self.current_phase]:
                self.phases[self.current_phase]["drill_down_decisions"] = []
            self.phases[self.current_phase]["drill_down_decisions"].append({
                "level": level, "decision": decision, "reasoning": reasoning, 
                "next_level": next_level, "timestamp": datetime.now().isoformat()
            })
    
    def log_level_start(self, level: int, dimension_value: str, message: str = ""):
        """Log the start of a hierarchy level analysis."""
        if not self.enabled:
            return
        log_msg = f"Level {level} Analysis Started"
        if message: log_msg += f" | {message}"
        self.logger.info("="*80)
        self.logger.info(log_msg)
        self.logger.info(f"  Target: {dimension_value}")
        self.logger.info("="*80)
        if self.current_phase:
            if "level_analysis" not in self.phases[self.current_phase]:
                self.phases[self.current_phase]["level_analysis"] = []
            self.phases[self.current_phase]["level_analysis"].append({
                "level": level, "status": "started", "start_time": time.time(),
                "start_timestamp": datetime.now().isoformat(), "message": message
            })
    
    def log_level_complete(self, level: int, dimension_value: str, summary: Optional[Dict[str, Any]] = None):
        """Log the completion of a hierarchy level analysis."""
        if not self.enabled:
            return
        self.logger.info("="*80)
        self.logger.info(f"Level {level} Analysis Complete")
        if summary: self.logger.info(f"  Summary: {json.dumps(summary, indent=2)}")
        self.logger.info("="*80)
        if self.current_phase and "level_analysis" in self.phases[self.current_phase]:
            for rec in self.phases[self.current_phase]["level_analysis"]:
                if rec["level"] == level and rec.get("status") == "started":
                    rec["status"] = "completed"
                    rec["end_time"] = time.time()
                    rec["end_timestamp"] = datetime.now().isoformat()
                    rec["duration_seconds"] = rec["end_time"] - rec["start_time"]
                    rec["summary"] = summary or {}
                    break
    
    def log_code_path(self, agent_name: str, path: str, reason: str = ""):
        """Log which execution path (code vs. LLM) was used for an agent stage.

        Args:
            agent_name: Name of the agent or stage.
            path: Either "code" (deterministic) or "llm" (language-model).
            reason: Optional reason / env-var controlling the selection.
        """
        if not self.enabled:
            return
        msg = f"[CodePath] {agent_name}: {path.upper()} path"
        if reason:
            msg += f" ({reason})"
        self.logger.info(msg)
        if self.current_phase:
            if "code_paths" not in self.phases[self.current_phase]:
                self.phases[self.current_phase]["code_paths"] = []
            self.phases[self.current_phase]["code_paths"].append({
                "agent": agent_name,
                "path": path,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
            })

    def log_agent_output(self, agent_name: str, output_summary: Dict[str, Any]):
        """Log the output from a specific agent."""
        if not self.enabled:
            return
        self.logger.info(f"[{agent_name}] Output:")
        self.logger.info(f"  {json.dumps(self._sanitize_data(output_summary), indent=2)}")
        if self.current_phase:
            if "agent_outputs" not in self.phases[self.current_phase]:
                self.phases[self.current_phase]["agent_outputs"] = []
            self.phases[self.current_phase]["agent_outputs"].append({
                "agent": agent_name, "output": self._sanitize_data(output_summary),
                "timestamp": datetime.now().isoformat()
            })


def phase_logged(phase_name: str, description: str = ""):
    """Decorator to automatically log phase start/end."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(self, ctx, *args, **kwargs):
            phase_logger = ctx.session.state.get("phase_logger")
            if not phase_logger:
                val = ctx.session.state.get("dimension_value")
                phase_logger = PhaseLogger(dimension_value=val)
                ctx.session.state["phase_logger"] = phase_logger
            
            input_data = {
                "dimension_value": ctx.session.state.get("dimension_value"),
                "state_keys": list(ctx.session.state.keys())[:10]
            }
            phase_logger.start_phase(phase_name, description, input_data)
            
            try:
                result = await func(self, ctx, *args, **kwargs)
                output_data = {
                    "result_type": type(result).__name__,
                    "result_keys": list(result.keys())[:10] if isinstance(result, dict) else None
                }
                phase_logger.end_phase(phase_name, output_data, status="completed")
                return result
            except Exception as e:
                phase_logger.log_error(f"Phase failed: {str(e)}", e)
                phase_logger.end_phase(phase_name, status="failed")
                raise
        
        @wraps(func)
        def sync_wrapper(self, ctx, *args, **kwargs):
            phase_logger = ctx.session.state.get("phase_logger")
            if not phase_logger:
                val = ctx.session.state.get("dimension_value")
                phase_logger = PhaseLogger(dimension_value=val)
                ctx.session.state["phase_logger"] = phase_logger
            
            input_data = {
                "dimension_value": ctx.session.state.get("dimension_value"),
                "state_keys": list(ctx.session.state.keys())[:10]
            }
            phase_logger.start_phase(phase_name, description, input_data)
            
            try:
                result = func(self, ctx, *args, **kwargs)
                output_data = {
                    "result_type": type(result).__name__,
                    "result_keys": list(result.keys())[:10] if isinstance(result, dict) else None
                }
                phase_logger.end_phase(phase_name, output_data, status="completed")
                return result
            except Exception as e:
                phase_logger.log_error(f"Phase failed: {str(e)}", e)
                phase_logger.end_phase(phase_name, status="failed")
                raise
        
        import inspect
        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# Global convenience functions
_global_logger = None

def get_phase_logger(dimension_value: Optional[str] = None) -> PhaseLogger:
    """Get or create a global phase logger."""
    global _global_logger
    if _global_logger is None or (dimension_value and _global_logger.dimension_value != dimension_value):
        _global_logger = PhaseLogger(dimension_value=dimension_value)
    return _global_logger

def log_phase_start(phase_name: str, description: str = "", input_data: Optional[Dict[str, Any]] = None):
    get_phase_logger().start_phase(phase_name, description, input_data)

def log_phase_end(phase_name: str, output_data: Optional[Dict[str, Any]] = None, status: str = "completed"):
    get_phase_logger().end_phase(phase_name, output_data, status)

def log_metric(metric_name: str, value: Any):
    get_phase_logger().log_metric(metric_name, value)

def log_error(error_message: str, exception: Optional[Exception] = None):
    get_phase_logger().log_error(error_message, exception)

def log_warning(warning_message: str):
    get_phase_logger().log_warning(warning_message)

def log_code_path(agent_name: str, path: str, reason: str = ""):
    """Log which execution path (code vs. LLM) was used for an agent stage."""
    get_phase_logger().log_code_path(agent_name, path, reason)
