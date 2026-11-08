"""Include D1 tenant schema checks in the repository-wide pytest suite."""

from cloudflare.tests.test_tenant_auth_schema import (
    TenantAuthSchemaTests as TestTenantAuthSchema,
)
