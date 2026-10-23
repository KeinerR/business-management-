from tenantdata.models import Account


PUC_STARTER = (
    ("1", "Activo", Account.ASSET, Account.DEBIT, None, False),
    ("11", "Disponible", Account.ASSET, Account.DEBIT, "1", False),
    ("1105", "Caja", Account.ASSET, Account.DEBIT, "11", False),
    ("110505", "Caja general", Account.ASSET, Account.DEBIT, "1105", True),
    ("1110", "Bancos", Account.ASSET, Account.DEBIT, "11", True),
    ("13", "Deudores", Account.ASSET, Account.DEBIT, "1", False),
    ("1305", "Clientes", Account.ASSET, Account.DEBIT, "13", True),
    ("2", "Pasivo", Account.LIABILITY, Account.CREDIT, None, False),
    ("22", "Proveedores", Account.LIABILITY, Account.CREDIT, "2", False),
    ("2205", "Proveedores nacionales", Account.LIABILITY, Account.CREDIT, "22", True),
    ("24", "Impuestos, gravámenes y tasas", Account.LIABILITY, Account.CREDIT, "2", False),
    ("2408", "Impuesto sobre las ventas por pagar", Account.LIABILITY, Account.CREDIT, "24", True),
    ("3", "Patrimonio", Account.EQUITY, Account.CREDIT, None, False),
    ("31", "Capital social", Account.EQUITY, Account.CREDIT, "3", True),
    ("4", "Ingresos", Account.INCOME, Account.CREDIT, None, False),
    ("41", "Ingresos operacionales", Account.INCOME, Account.CREDIT, "4", False),
    ("4135", "Comercio y servicios", Account.INCOME, Account.CREDIT, "41", True),
    ("5", "Gastos", Account.EXPENSE, Account.DEBIT, None, False),
    ("51", "Gastos operacionales de administración", Account.EXPENSE, Account.DEBIT, "5", False),
    ("5105", "Gastos de personal", Account.EXPENSE, Account.DEBIT, "51", True),
    ("5110", "Honorarios", Account.EXPENSE, Account.DEBIT, "51", True),
    ("5135", "Servicios", Account.EXPENSE, Account.DEBIT, "51", True),
    ("6", "Costos de ventas", Account.COST, Account.DEBIT, None, False),
    ("61", "Costo de ventas y prestación de servicios", Account.COST, Account.DEBIT, "6", True),
)


def seed_puc_starter(business):
    accounts = {}
    created = 0
    for code, name, account_type, nature, parent_code, accepts_entries in PUC_STARTER:
        account, was_created = Account.objects.update_or_create(
            business=business,
            code=code,
            defaults={"name": name, "account_type": account_type, "nature": nature, "parent": accounts.get(parent_code), "accepts_entries": accepts_entries, "is_active": True},
        )
        accounts[code] = account
        created += int(was_created)
    return created, len(PUC_STARTER)
