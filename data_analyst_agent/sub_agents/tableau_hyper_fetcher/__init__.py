"""
tableau_hyper_fetcher
=====================

Generic sub-agent for loading data from Tableau TDSX / Hyper files directly
via the Tableau HyperAPI, without requiring a running A2A server.

Usage::

    from data_analyst_agent.sub_agents.tableau_hyper_fetcher import TableauHyperFetcher

    fetcher = TableauHyperFetcher()
"""

from .fetcher import TableauHyperFetcher

__all__ = ["TableauHyperFetcher"]
