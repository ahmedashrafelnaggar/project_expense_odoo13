from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class ProjectExpenseRequest(models.Model):
    _name = 'project.expense.request'
    _description = 'Project Expense Request'

    # Fields for the Expense Request
    name = fields.Char(string="Reference", required=True, copy=False, default='New')
    date = fields.Date(string='Request Date', default=fields.Date.context_today)
    project_id = fields.Many2one('project.project', string='Project', domain=[('active', '=', True)], required=True)
    expense_amount = fields.Monetary(related='project_id.expense_amount',string="Expense Amount")
    project_manager = fields.Many2one('res.users', string='Project Manager', related='project_id.user_id', readonly=True)
    expense_type_id = fields.Many2one('expense.type', string='Expense Type', required=True)
    limit = fields.Float(related='expense_type_id.limit')
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], default='draft', string="State")
    expense_line_ids = fields.One2many('project.expense.request.line', 'expense_request_id', string="Expense Lines", required=True)
    expense_type_ids = fields.Many2many('expense.type', string="Expense Types")
    total_amount = fields.Float(string="Total Amount", compute="_compute_total_amount", store=True)
    task_count = fields.Integer('Number of Tasks', compute='_compute_task_count', store=True)
    product_line_ids = fields.One2many('product.line', 'request_id', string='Product Lines')
    picking_id = fields.Many2one('stock.picking', string='Related Picking', readonly=True)

    # Method to check the amount against the expense type's limit
    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            total_limit = sum(expense.limit for expense in record.expense_type_ids)
            if record.amount > total_limit:
                raise ValidationError("Amount cannot exceed the total limit of selected expense types.")
            if record.amount <= 0:
                raise ValidationError("Amount must be greater than 0.")

    @api.depends('expense_line_ids.amount')
    def _compute_total_amount(self):
        for record in self:
            record.total_amount = sum(line.amount for line in record.expense_line_ids)

    @api.depends('project_id')
    def _compute_task_count(self):
        for record in self:
            record.task_count = len(record.project_id.task_ids)

    def unlink(self):
        for record in self:
            if record.state == 'done':
                raise UserError("You cannot delete a record in the 'Done' state.")
        return super(ProjectExpenseRequest, self).unlink()

    def copy(self, default=None):
        for record in self:
            if record.state == 'done':
                raise UserError("You cannot copy an expense request that is in the 'Done' state.")
        return super(ProjectExpenseRequest, self).copy(default)

    def write(self, vals):
        res = super(ProjectExpenseRequest, self).write(vals)
        for record in self:
            if 'state' in vals and vals['state'] == 'done':
                total_amount = sum(line.amount for line in record.expense_line_ids)
                record.project_id.expense_amount += total_amount
        return res

    def open_wizard(self):
        action = self.env.ref('project_expense.action_project_expense_report_wizard').read()[0]
        return action

    def action_draft(self):
        for rec in self:
            if rec.state == 'cancel':
                rec.state = 'draft'

    def action_confirmed(self):
        for rec in self:
            rec.state = 'confirmed'

    def action_approved(self):
        for rec in self:
            rec.state = 'approved'

    def action_done(self):
        self.state = 'done'
        self._create_out_picking()


    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'

    def action_approve(self):
        self.state = 'approved'
        total_expense = sum(line.amount for line in self.expense_type_ids)
        self.project_id.expense_amount += total_expense

    def _create_out_picking(self):
        picking_model = self.env['stock.picking']
        move_model = self.env['stock.move']

        # Create the picking
        picking = picking_model.create({
            'partner_id': self.project_id.partner_id.id,  # Assuming project has a partner
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'location_id': self.env['stock.warehouse'].search([], limit=1).lot_stock_id.id,
            # Replace with your logic to get the correct location
            'location_dest_id': self.project_id.partner_id.property_stock_customer.id,
            'move_lines': [],
        })

        # Create stock moves for each product line
        for line in self.product_line_ids:
            move_model.create({
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })

        # Confirm and assign the picking
        picking.action_confirm()
        picking.action_assign()

    def open_picking(self):
        """Return an action to open the related stock picking."""
        if self.picking_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Related Picking',
                'res_model': 'stock.picking',
                'res_id': self.picking_id.id,
                'view_mode': 'form',
                'view_type': 'form',
                'target': 'current',  # Open in the same window
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'No Picking Found',
                'res_model': 'project.expense.request',
                'view_mode': 'form',
                'res_id': self.id,
                'target': 'current',
                'context': {'message': 'No related picking found for this expense request.'},
            }



class ProjectExpenseRequestLine(models.Model):
    _name = 'project.expense.request.line'
    _description = 'Project Expense Request Line'

    expense_request_id = fields.Many2one('project.expense.request', string="Expense Request", required=True, ondelete='cascade')
    limit = fields.Float(related='expense_request_id.limit')
    expense_type_id = fields.Many2one('expense.type', string="Expense Type")
    amount = fields.Monetary(string='Amount', required=True, related='expense_request_id.amount')
    currency_id = fields.Many2one(related='expense_request_id.currency_id', string="Currency", store=True, readonly=True)

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError("The amount must be greater than 0.")
            if record.amount > record.limit:
                raise ValidationError(
                    f"The amount cannot exceed the limit of {record.limit}."
                )