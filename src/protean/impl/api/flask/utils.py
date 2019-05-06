""" Utility functions used by Protean Flask"""


def immutable_dict_2_dict(imm_dict):
    """ Function to convert an Immutable Dictionary to a Mutable one
    Convert multi valued and keys ending with [] to lists
    """
    m_dict = {}

    for key, val in imm_dict.to_dict(flat=False).items():
        if len(val) > 1 or key.endswith('[]'):
            m_dict[key.strip('[]')] = val
        else:
            m_dict[key] = val[0]

    return m_dict


def derive_tenant(url):
    """Derive tenant ID from host

    We consider the standard `subdomain.domain.com` structure to be the
    `tenant_id`.

    There might be multiple applications that are hosted for the subdomain,
    and they may have additional application identifiers at the beginning,
    like 'customers.subdomain.domain.com' or 'backoffice.subdomain.domain.com'.
    In all such cases, we still consider the 3 part structure,
     `subdomain.domain.com`, to be the `tenant_id`.

    """

    from urllib.parse import urlparse

    host = urlparse(url).hostname

    return host
