-- ETVS migration 003: ballot security validation
-- Run after migrations 001 and 002 on an existing PostgreSQL database.

/*
===============================================================================
BALLOT SECURITY FEATURES
===============================================================================
Each contest ballot must pass every required security feature to be valid.
A ballot failing one or more required security features is rejected.
A physically damaged ballot is spoilt and is excluded from votes cast/turnout.
===============================================================================
*/
