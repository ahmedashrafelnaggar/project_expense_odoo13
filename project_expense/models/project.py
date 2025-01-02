from odoo import models, fields

class Project(models.Model):
    _inherit = 'project.project'

    # expense_amount = fields.Float(string='Expense Amount', default=0.0, help="Total expense amount for the project")
    # Create a monetary field for expense amount with the currency set to the company's currency
    expense_amount = fields.Monetary(
        string='Expense Amount',
        default=0.0,
        currency_field='currency_id',
        help="Total expense amount for the project"
    )
    currency_id = fields.Many2one('res.currency')

