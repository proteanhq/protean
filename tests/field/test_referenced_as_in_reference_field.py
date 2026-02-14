import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields.basic import String, Integer
from protean.fields.association import Reference, HasMany, HasOne
from protean.utils.reflection import attributes


class Book(BaseAggregate):
    title = String(max_length=50)
    isbn = String(identifier=True, max_length=13)
    comments = HasMany("Comment", via="isbn")


class Comment(BaseEntity):
    content = String(max_length=50)
    book = Reference(Book, referenced_as="isbn")


class Author(BaseAggregate):
    name = String(max_length=50)
    # Default behavior - would create 'author_id' foreign key
    posts_default = HasMany("BlogPost")
    # With via - uses custom foreign key name
    posts_custom = HasMany("BlogPost", via="author_uuid")


class BlogPost(BaseEntity):
    title = String(max_length=100)
    author_id = String()  # Default foreign key
    author_uuid = String()  # Custom foreign key via 'via' parameter


class Course(BaseAggregate):
    name = String(max_length=100)
    course_id = String(identifier=True, max_length=10)
    instructor = HasOne("Instructor", via="course_assigned")


class Instructor(BaseEntity):
    name = String(max_length=100)
    course_assigned = String()


class Project(BaseAggregate):
    name = String(max_length=100)
    project_code = String(identifier=True, max_length=10)
    lead_developer = HasOne("Developer", via="project_ref")


class Developer(BaseEntity):
    name = String(max_length=100)
    skill_level = String(max_length=50)
    project_ref = String()


def test_structure_of_entity_with_reference_field(test_domain):
    attrs = attributes(Comment)
    missing = [key for key in ["content", "isbn", "id"] if key not in attrs]
    assert not missing, f"Missing keys: {missing}"


@pytest.mark.database
class TestViaInAssociationField:
    """Test cases for the via parameter in Association fields (HasMany and HasOne)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Book)
        test_domain.register(Comment, part_of=Book)
        test_domain.register(Author)
        test_domain.register(BlogPost, part_of=Author)
        test_domain.register(Course)
        test_domain.register(Instructor, part_of=Course)
        test_domain.register(Project)
        test_domain.register(Developer, part_of=Project)
        test_domain.init(traverse=False)

    def test_has_many_with_via_parameter_uses_custom_foreign_key(self, test_domain):
        """Test that HasMany with via parameter uses the specified field name for foreign key."""
        book = Book(title="1984", isbn="9780451524935")
        comment = Comment(content="Great book!")
        book.add_comments(comment)

        # Verify that the via parameter creates the correct foreign key field
        assert hasattr(comment, "isbn")
        assert comment.isbn == book.isbn
        assert comment.isbn == "9780451524935"

    def test_has_many_with_via_parameter_persistence(self, test_domain):
        """Test that HasMany with via parameter persists and retrieves correctly."""
        book = Book(title="Animal Farm", isbn="9780451526342")
        comment1 = Comment(content="Brilliant allegory!")
        comment2 = Comment(content="Timeless classic")

        book.add_comments([comment1, comment2])
        test_domain.repository_for(Book).add(book)

        # Retrieve and verify
        retrieved_book = test_domain.repository_for(Book).get(book.isbn)

        assert len(retrieved_book.comments) == 2
        assert retrieved_book.comments[0].isbn == book.isbn
        assert retrieved_book.comments[1].isbn == book.isbn

        # Verify content
        comment_contents = [c.content for c in retrieved_book.comments]
        assert "Brilliant allegory!" in comment_contents
        assert "Timeless classic" in comment_contents

    def test_has_many_with_via_parameter_linked_attribute_method(self, test_domain):
        """Test that _linked_attribute method returns the via value when specified."""
        has_many_field = Book.__dict__["comments"]

        # The _linked_attribute should return 'isbn' because of via="isbn"
        linked_attr = has_many_field._linked_attribute(Book)
        assert linked_attr == "isbn"

    def test_has_many_with_via_parameter_vs_default_behavior(self, test_domain):
        """Test comparison between via parameter and default foreign key naming."""
        default_field = Author.__dict__["posts_default"]
        custom_field = Author.__dict__["posts_custom"]

        default_linked_attr = default_field._linked_attribute(Author)
        custom_linked_attr = custom_field._linked_attribute(Author)

        assert default_linked_attr == "author_id"  # Default behavior
        assert custom_linked_attr == "author_uuid"  # Via parameter

    def test_has_many_with_via_parameter_add_and_remove(self, test_domain):
        """Test adding and removing items with via parameter."""
        book = Book(title="Brave New World", isbn="9780060850524")
        comment1 = Comment(content="Dystopian masterpiece")
        comment2 = Comment(content="Thought-provoking")
        comment3 = Comment(content="Excellent world-building")

        # Add comments
        book.add_comments([comment1, comment2])
        assert len(book.comments) == 2
        assert comment1.isbn == book.isbn
        assert comment2.isbn == book.isbn

        # Add one more
        book.add_comments(comment3)
        assert len(book.comments) == 3
        assert comment3.isbn == book.isbn

        # Remove one
        book.remove_comments(comment2)
        assert len(book.comments) == 2
        remaining_comments = [c.content for c in book.comments]
        assert "Thought-provoking" not in remaining_comments
        assert "Dystopian masterpiece" in remaining_comments
        assert "Excellent world-building" in remaining_comments

    def test_has_many_with_via_parameter_filter_and_get_methods(self, test_domain):
        """Test filter and get methods work with via parameter."""
        book = Book(title="The Great Gatsby", isbn="9780743273565")
        comment1 = Comment(content="Beautiful prose")
        comment2 = Comment(content="Tragic story")
        comment3 = Comment(content="American classic")

        book.add_comments([comment1, comment2, comment3])

        # Test filter
        filtered_comments = book.filter_comments(content="Beautiful prose")
        assert len(filtered_comments) == 1
        assert filtered_comments[0].content == "Beautiful prose"
        assert filtered_comments[0].isbn == book.isbn

        # Test get
        found_comment = book.get_one_from_comments(content="Tragic story")
        assert found_comment.content == "Tragic story"
        assert found_comment.isbn == book.isbn

    def test_has_many_with_via_parameter_empty_assignment(self, test_domain):
        """Test assigning empty list to HasMany with via parameter."""
        book = Book(title="To Kill a Mockingbird", isbn="9780061120084")
        comment = Comment(content="Powerful message")

        book.add_comments(comment)
        assert len(book.comments) == 1

        # Assign empty list
        book.comments = []
        assert len(book.comments) == 0

    def test_has_many_with_via_parameter_dictionary_assignment(self, test_domain):
        """Test assigning dictionary values to HasMany with via parameter."""
        book = Book(title="Pride and Prejudice", isbn="9780141439518")

        # Assign dictionary values - should be converted to Comment objects
        book.comments = [
            {"content": "Witty dialogue"},
            {"content": "Character development"},
        ]

        assert len(book.comments) == 2
        assert all(isinstance(c, Comment) for c in book.comments)
        assert book.comments[0].content == "Witty dialogue"
        assert book.comments[1].content == "Character development"
        assert book.comments[0].isbn == book.isbn
        assert book.comments[1].isbn == book.isbn

    def test_via_parameter_persistence_with_database(self, test_domain):
        """Test that via parameter works correctly with database persistence."""
        book = Book(title="Database Testing", isbn="9781234567890")
        comment1 = Comment(content="Excellent database coverage")
        comment2 = Comment(content="Well structured tests")

        book.add_comments([comment1, comment2])
        test_domain.repository_for(Book).add(book)

        # Clear any caches and retrieve fresh from database
        book_repo = test_domain.repository_for(Book)
        retrieved_book = book_repo.get(book.isbn)

        # Verify persistence
        assert len(retrieved_book.comments) == 2
        assert all(c.isbn == book.isbn for c in retrieved_book.comments)

        # Verify we can add more comments and persist again
        comment3 = Comment(content="Additional test comment")
        retrieved_book.add_comments(comment3)
        book_repo.add(retrieved_book)

        # Retrieve again to verify the additional comment was persisted
        final_book = book_repo.get(book.isbn)
        assert len(final_book.comments) == 3

    def test_via_parameter_deletion_persistence(self, test_domain):
        """Test deleting associations with via parameter persists correctly."""

        course = Course(name="Python Programming", course_id="PY101")
        instructor = Instructor(name="Dr. Python")
        course.instructor = instructor

        test_domain.repository_for(Course).add(course)

        # Retrieve and remove instructor
        retrieved_course = test_domain.repository_for(Course).get(course.course_id)
        assert retrieved_course.instructor == instructor
        assert retrieved_course.instructor.course_assigned == course.course_id
        assert instructor.course.instructor.course == course

        retrieved_course.instructor = None
        test_domain.repository_for(Course).add(retrieved_course)

        # Verify deletion persisted
        final_course = test_domain.repository_for(Course).get(course.course_id)
        assert final_course.instructor is None

    def test_via_parameter_update_persistence(self, test_domain):
        """Test updating entities with via parameter persists correctly."""
        project = Project(name="AI Platform", project_code="AI001")
        developer = Developer(name="Sarah Connor", skill_level="Senior")
        project.lead_developer = developer

        test_domain.repository_for(Project).add(project)

        # Retrieve and update
        retrieved_project = test_domain.repository_for(Project).get(
            project.project_code
        )
        retrieved_project.lead_developer.skill_level = "Principal"
        test_domain.repository_for(Project).add(retrieved_project)

        # Verify update persisted
        final_project = test_domain.repository_for(Project).get(project.project_code)
        assert final_project.lead_developer.skill_level == "Principal"
        assert final_project.lead_developer.project_ref == project.project_code


def test_has_one_with_via_parameter_uses_custom_foreign_key(test_domain):
    """Test that HasOne with via parameter uses the specified field name for foreign key."""

    # Create classes with HasOne using via parameter
    class University(BaseAggregate):
        name = String(max_length=100)
        code = String(identifier=True, max_length=10)
        main_campus = HasOne("Campus", via="university_code")

    class Campus(BaseEntity):
        name = String(max_length=100)
        university_code = String()  # Custom foreign key field via 'via' parameter

    test_domain.register(University)
    test_domain.register(Campus, part_of=University)
    test_domain.init(traverse=False)

    university = University(name="MIT", code="MIT001")
    campus = Campus(name="Main Campus")
    university.main_campus = campus

    # Verify that the via parameter creates the correct foreign key field
    assert hasattr(campus, "university_code")
    assert campus.university_code == university.code
    assert campus.university_code == "MIT001"


def test_has_one_with_via_parameter_persistence(test_domain):
    """Test that HasOne with via parameter persists and retrieves correctly."""

    class Company(BaseAggregate):
        name = String(max_length=100)
        registration_number = String(identifier=True, max_length=20)
        headquarters = HasOne("Office", via="company_reg_num")

    class Office(BaseEntity):
        address = String(max_length=200)
        company_reg_num = String()  # Custom foreign key field

    test_domain.register(Company)
    test_domain.register(Office, part_of=Company)
    test_domain.init(traverse=False)

    company = Company(name="Tech Corp", registration_number="TC12345")
    office = Office(address="123 Tech Street, Silicon Valley")
    company.headquarters = office

    test_domain.repository_for(Company).add(company)

    # Retrieve and verify
    retrieved_company = test_domain.repository_for(Company).get(
        company.registration_number
    )

    assert retrieved_company.headquarters is not None
    assert retrieved_company.headquarters.address == "123 Tech Street, Silicon Valley"
    assert retrieved_company.headquarters.company_reg_num == company.registration_number


def test_has_one_with_via_parameter_linked_attribute_method(test_domain):
    """Test that _linked_attribute method returns the via value for HasOne when specified."""

    class School(BaseAggregate):
        name = String(max_length=100)
        school_id = String(identifier=True, max_length=10)
        principal = HasOne("Principal", via="school_identifier")

    class Principal(BaseEntity):
        name = String(max_length=100)
        school_identifier = String()

    test_domain.register(School)
    test_domain.register(Principal, part_of=School)
    test_domain.init(traverse=False)

    school_field = School.__dict__["principal"]

    # The _linked_attribute should return 'school_identifier' because of via="school_identifier"
    linked_attr = school_field._linked_attribute(School)
    assert linked_attr == "school_identifier"


def test_has_one_with_via_parameter_vs_default_behavior(test_domain):
    """Test comparison between via parameter and default foreign key naming for HasOne."""

    class Department(BaseAggregate):
        name = String(max_length=100)
        # Default behavior - would create 'department_id' foreign key
        manager_default = HasOne("Manager")
        # With via - uses custom foreign key name
        manager_custom = HasOne("Manager", via="dept_code")

    class Manager(BaseEntity):
        name = String(max_length=100)
        department_id = String()  # Default foreign key
        dept_code = String()  # Custom foreign key via 'via' parameter

    test_domain.register(Department)
    test_domain.register(Manager, part_of=Department)
    test_domain.init(traverse=False)

    # Test _linked_attribute method
    default_field = Department.__dict__["manager_default"]
    custom_field = Department.__dict__["manager_custom"]

    default_linked_attr = default_field._linked_attribute(Department)
    custom_linked_attr = custom_field._linked_attribute(Department)

    assert default_linked_attr == "department_id"  # Default behavior
    assert custom_linked_attr == "dept_code"  # Via parameter


def test_has_one_with_via_parameter_assignment_and_removal(test_domain):
    """Test assigning and removing HasOne with via parameter."""

    class Store(BaseAggregate):
        name = String(max_length=100)
        store_code = String(identifier=True, max_length=10)
        cashier = HasOne("Cashier", via="assigned_store")

    class Cashier(BaseEntity):
        name = String(max_length=100)
        assigned_store = String()

    test_domain.register(Store)
    test_domain.register(Cashier, part_of=Store)
    test_domain.init(traverse=False)

    store = Store(name="Main Store", store_code="MS001")
    cashier1 = Cashier(name="John Doe")
    cashier2 = Cashier(name="Jane Smith")

    # Assign cashier
    store.cashier = cashier1
    assert store.cashier == cashier1
    assert cashier1.assigned_store == store.store_code

    # Replace with another cashier
    store.cashier = cashier2
    assert store.cashier == cashier2
    assert cashier2.assigned_store == store.store_code

    # Remove cashier
    store.cashier = None
    assert store.cashier is None


def test_has_one_with_via_parameter_dictionary_assignment(test_domain):
    """Test assigning dictionary value to HasOne with via parameter."""

    class Restaurant(BaseAggregate):
        name = String(max_length=100)
        license_number = String(identifier=True, max_length=15)
        chef = HasOne("Chef", via="restaurant_license")

    class Chef(BaseEntity):
        name = String(max_length=100)
        specialty = String(max_length=100)
        restaurant_license = String()

    test_domain.register(Restaurant)
    test_domain.register(Chef, part_of=Restaurant)
    test_domain.init(traverse=False)

    restaurant = Restaurant(name="Fine Dining", license_number="FD123456")

    # Assign dictionary value - should be converted to Chef object
    restaurant.chef = {"name": "Gordon Ramsay", "specialty": "Modern European"}

    assert isinstance(restaurant.chef, Chef)
    assert restaurant.chef.name == "Gordon Ramsay"
    assert restaurant.chef.specialty == "Modern European"
    assert restaurant.chef.restaurant_license == restaurant.license_number


def test_has_one_with_via_parameter_update_scenarios(test_domain):
    """Test various update scenarios for HasOne with via parameter."""

    class Bank(BaseAggregate):
        name = String(max_length=100)
        swift_code = String(identifier=True, max_length=15)
        branch_manager = HasOne("BranchManager", via="bank_swift")

    class BranchManager(BaseEntity):
        name = String(max_length=100)
        experience_years = String()
        bank_swift = String()

    test_domain.register(Bank)
    test_domain.register(BranchManager, part_of=Bank)
    test_domain.init(traverse=False)

    bank = Bank(name="Global Bank", swift_code="GLBK123")
    manager1 = BranchManager(name="Alice Johnson", experience_years="10")
    manager2 = BranchManager(name="Bob Wilson", experience_years="15")

    # Initial assignment
    bank.branch_manager = manager1
    assert bank.branch_manager == manager1
    assert manager1.bank_swift == bank.swift_code

    # Update to new manager
    bank.branch_manager = manager2
    assert bank.branch_manager == manager2
    assert manager2.bank_swift == bank.swift_code

    # Update existing manager's attributes
    manager2.experience_years = "16"
    assert bank.branch_manager.experience_years == "16"


def test_via_parameter_with_none_value(test_domain):
    """Test via parameter behavior when set to None."""

    # Create a field with via=None (should behave like default)
    class Library(BaseAggregate):
        name = String(max_length=100)
        books = HasMany("LibraryBook", via=None)

    class LibraryBook(BaseEntity):
        title = String(max_length=100)
        library_id = String()

    test_domain.register(Library)
    test_domain.register(LibraryBook, part_of=Library)
    test_domain.init(traverse=False)

    library_field = Library.__dict__["books"]

    # Should use default behavior when via=None
    linked_attr = library_field._linked_attribute(Library)
    assert linked_attr == "library_id"  # Default behavior


def test_via_parameter_with_empty_string(test_domain):
    """Test via parameter behavior when set to empty string."""

    class Museum(BaseAggregate):
        name = String(max_length=100)
        # Empty string should be treated as falsy and use default
        exhibits = HasMany("Exhibit", via="")

    class Exhibit(BaseEntity):
        name = String(max_length=100)
        museum_id = String()

    test_domain.register(Museum)
    test_domain.register(Exhibit, part_of=Museum)
    test_domain.init(traverse=False)

    museum_field = Museum.__dict__["exhibits"]

    # Empty string should use default behavior
    linked_attr = museum_field._linked_attribute(Museum)
    assert linked_attr == "museum_id"  # Default behavior


def test_via_parameter_with_different_data_types(test_domain):
    """Test via parameter with different field data types."""

    class Team(BaseAggregate):
        name = String(max_length=100)
        team_number = String(identifier=True, max_length=10)
        captain = HasOne("Player", via="team_num")

    class Player(BaseEntity):
        name = String(max_length=100)
        team_num = String()  # String field for foreign key

    test_domain.register(Team)
    test_domain.register(Player, part_of=Team)
    test_domain.init(traverse=False)

    team = Team(name="Warriors", team_number="W001")
    player = Player(name="Michael Jordan")
    team.captain = player

    assert player.team_num == "W001"
    assert isinstance(player.team_num, str)


def test_via_parameter_with_multiple_associations_to_same_entity(test_domain):
    """Test multiple association fields with different via parameters pointing to same entity."""

    class Organization(BaseAggregate):
        name = String(max_length=100)
        org_code = String(identifier=True, max_length=10)
        # Multiple associations to the same entity type with different via parameters
        employees = HasMany("Person", via="employer_code")
        contractors = HasMany("Person", via="contractor_for")

    class Person(BaseEntity):
        name = String(max_length=100)
        employer_code = String()  # For employees
        contractor_for = String()  # For contractors

    test_domain.register(Organization)
    test_domain.register(Person, part_of=Organization)
    test_domain.init(traverse=False)

    org = Organization(name="Tech Company", org_code="TC001")
    employee = Person(name="John Employee")
    contractor = Person(name="Jane Contractor")

    org.add_employees(employee)
    org.add_contractors(contractor)

    assert employee.employer_code == org.org_code
    assert contractor.contractor_for == org.org_code
    assert employee.contractor_for != org.org_code  # Should be None or empty
    assert contractor.employer_code != org.org_code  # Should be None or empty


def test_via_parameter_preserves_type_during_assignment(test_domain):
    """Test that via parameter preserves the type of the identifier field."""

    class Warehouse(BaseAggregate):
        name = String(max_length=100)
        warehouse_id = String(identifier=True, max_length=10)
        inventory_manager = HasOne("InventoryManager", via="warehouse_ref")

    class InventoryManager(BaseEntity):
        name = String(max_length=100)
        warehouse_ref = String()

    test_domain.register(Warehouse)
    test_domain.register(InventoryManager, part_of=Warehouse)
    test_domain.init(traverse=False)

    warehouse = Warehouse(name="Central Warehouse", warehouse_id="CW123")
    manager = InventoryManager(name="Alice Manager")

    warehouse.inventory_manager = manager

    # Verify the foreign key value and type are preserved correctly
    assert manager.warehouse_ref == warehouse.warehouse_id
    assert type(manager.warehouse_ref) is type(warehouse.warehouse_id)
    assert isinstance(manager.warehouse_ref, str)


def test_via_parameter_with_custom_identifier_field(test_domain):
    """Test via parameter when the aggregate has a custom identifier field."""

    class Vehicle(BaseAggregate):
        make = String(max_length=50)
        vin = String(identifier=True, max_length=17)  # Custom identifier
        parts = HasMany("VehiclePart", via="vehicle_vin")

    class VehiclePart(BaseEntity):
        name = String(max_length=100)
        part_number = String(max_length=50)
        vehicle_vin = String()  # Foreign key to VIN

    test_domain.register(Vehicle)
    test_domain.register(VehiclePart, part_of=Vehicle)
    test_domain.init(traverse=False)

    vehicle = Vehicle(make="Toyota", vin="1HGBH41JXMN109186")
    part1 = VehiclePart(name="Engine", part_number="ENG001")
    part2 = VehiclePart(name="Transmission", part_number="TRN001")

    vehicle.add_parts([part1, part2])

    # Verify the custom identifier is used correctly
    assert part1.vehicle_vin == vehicle.vin
    assert part2.vehicle_vin == vehicle.vin
    assert part1.vehicle_vin == "1HGBH41JXMN109186"


def test_via_parameter_with_composite_identifier_scenario(test_domain):
    """Test via parameter behavior when dealing with what would be composite key scenarios."""

    class Account(BaseAggregate):
        account_number = String(max_length=20)
        branch_code = String(identifier=True, max_length=10)  # Using branch as ID
        transactions = HasMany("Transaction", via="account_branch")

    class Transaction(BaseEntity):
        amount = String(max_length=20)
        transaction_type = String(max_length=50)
        account_branch = String()  # Links to branch_code

    test_domain.register(Account)
    test_domain.register(Transaction, part_of=Account)
    test_domain.init(traverse=False)

    account = Account(account_number="123456789", branch_code="BR001")
    transaction1 = Transaction(amount="100.00", transaction_type="deposit")
    transaction2 = Transaction(amount="50.00", transaction_type="withdrawal")

    account.add_transactions([transaction1, transaction2])

    # Verify linkage uses the identifier field (branch_code), not account_number
    assert transaction1.account_branch == account.branch_code
    assert transaction2.account_branch == account.branch_code
    assert transaction1.account_branch == "BR001"


def test_via_parameter_with_multiple_custom_identifiers(test_domain):
    """Test via parameter when multiple entities have custom identifier fields."""

    class Supplier(BaseAggregate):
        company_name = String(max_length=100)
        supplier_code = String(identifier=True, max_length=15)
        products = HasMany("Product", via="supplier_ref")

    class Product(BaseEntity):
        product_name = String(max_length=100)
        product_sku = String(
            identifier=True, max_length=20
        )  # Entity also has custom ID
        supplier_ref = String()

    test_domain.register(Supplier)
    test_domain.register(Product, part_of=Supplier)
    test_domain.init(traverse=False)

    supplier = Supplier(company_name="Tech Supplies Inc", supplier_code="TS12345")
    product1 = Product(product_name="Laptop", product_sku="LAP001")
    product2 = Product(product_name="Mouse", product_sku="MOU001")

    supplier.add_products([product1, product2])

    # Verify foreign key links to supplier's identifier
    assert product1.supplier_ref == supplier.supplier_code
    assert product2.supplier_ref == supplier.supplier_code

    # Verify products maintain their own identifiers
    assert product1.product_sku == "LAP001"
    assert product2.product_sku == "MOU001"


def test_via_parameter_field_initialization_order(test_domain):
    """Test that via parameter works regardless of field definition order."""

    class EventVenue(BaseAggregate):
        venue_name = String(max_length=100)
        # Define association before identifier to test initialization order
        events = HasMany("Event", via="venue_ref")
        venue_code = String(identifier=True, max_length=10)

    class Event(BaseEntity):
        event_name = String(max_length=100)
        venue_ref = String()

    test_domain.register(EventVenue)
    test_domain.register(Event, part_of=EventVenue)
    test_domain.init(traverse=False)

    venue = EventVenue(venue_name="Grand Hall", venue_code="GH001")
    event = Event(event_name="Annual Conference")

    venue.add_events(event)

    # Should work correctly despite field definition order
    assert event.venue_ref == venue.venue_code
    assert event.venue_ref == "GH001"


def test_via_parameter_with_integer_identifier(test_domain):
    """Test via parameter with non-string identifier fields."""

    class Region(BaseAggregate):
        name = String(max_length=100)
        region_id = Integer(identifier=True)
        offices = HasMany("Office", via="region_number")

    class Office(BaseEntity):
        office_name = String(max_length=100)
        region_number = Integer()

    test_domain.register(Region)
    test_domain.register(Office, part_of=Region)
    test_domain.init(traverse=False)

    region = Region(name="North America", region_id=1)
    office = Office(office_name="New York Office")

    region.add_offices(office)

    # Verify integer identifier is properly linked
    assert office.region_number == region.region_id
    assert office.region_number == 1
    assert isinstance(office.region_number, int)


def test_via_parameter_with_uuid_identifier(test_domain):
    """Test via parameter with UUID-like identifier fields."""

    class Patient(BaseAggregate):
        name = String(max_length=100)
        patient_uuid = String(identifier=True, max_length=36)
        medical_records = HasMany("MedicalRecord", via="patient_id")

    class MedicalRecord(BaseEntity):
        diagnosis = String(max_length=200)
        patient_id = String()  # Will store UUID

    test_domain.register(Patient)
    test_domain.register(MedicalRecord, part_of=Patient)
    test_domain.init(traverse=False)

    patient = Patient(
        name="John Doe", patient_uuid="550e8400-e29b-41d4-a716-446655440000"
    )
    record = MedicalRecord(diagnosis="Annual checkup - healthy")

    patient.add_medical_records(record)

    assert record.patient_id == patient.patient_uuid
    assert record.patient_id == "550e8400-e29b-41d4-a716-446655440000"
