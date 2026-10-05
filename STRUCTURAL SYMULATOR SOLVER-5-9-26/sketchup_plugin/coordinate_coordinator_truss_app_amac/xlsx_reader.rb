# xlsx_reader.rb
#
# A minimal, dependency-free XLSX reader for plain Ruby / SketchUp's bundled
# Ruby.  Counterpart to xlsx_writer.rb -- reads back the single "Model"
# sheet layout that apps/stereo/stereo_reports.export_excel produces.
#
# Only the standard library is used: 'zlib' for inflate and REXML for XML
# parsing.  Handles both inline-string cells (<is><t>…</t></is>) and
# shared-string cells (<v>idx</v> with t="s"), which openpyxl may emit.
require 'zlib'
require 'rexml/document'
require 'stringio'

module CoordinateCoordinatorTrussAppAMAC
  class XlsxReader
    attr_reader :sheets

    def initialize(path)
      @path = path
      @sheets = {}
      @shared_strings = []
      _parse
    end

    # Returns the sheet named +name+ as a 2-D array (0-indexed rows x cols).
    # Missing cells are nil.
    def sheet(name)
      @sheets[name]
    end

    private

    def _parse
      entries = _read_zip(@path)

      # Shared strings table (optional -- openpyxl uses it, our writer doesn't)
      sst_xml = entries['xl/sharedStrings.xml']
      if sst_xml
        doc = REXML::Document.new(sst_xml)
        doc.elements.each('//si') do |si|
          parts = []
          si.elements.each('.//t') { |t| parts << (t.text || '') }
          @shared_strings << parts.join
        end
      end

      # Find sheet names from workbook.xml
      wb_xml = entries['xl/workbook.xml']
      sheet_names = []
      if wb_xml
        doc = REXML::Document.new(wb_xml)
        doc.elements.each('//sheet') do |el|
          sheet_names << el.attributes['name']
        end
      end

      # Read each worksheet
      sheet_names.each_with_index do |name, i|
        key = "xl/worksheets/sheet#{i + 1}.xml"
        xml = entries[key]
        next unless xml
        @sheets[name] = _parse_sheet(xml)
      end
    end

    def _parse_sheet(xml)
      doc = REXML::Document.new(xml)
      rows = {}
      max_row = 0
      max_col = 0

      doc.elements.each('//row') do |row_el|
        row_el.elements.each('c') do |cell_el|
          ref = cell_el.attributes['r']
          col, row = _ref_to_rc(ref)
          max_row = row if row > max_row
          max_col = col if col > max_col

          type = cell_el.attributes['t']
          v_el = cell_el.elements['v']
          is_el = cell_el.elements['is']

          value = nil
          if type == 'inlineStr' && is_el
            t_el = is_el.elements['t']
            value = t_el ? (t_el.text || '') : ''
          elsif type == 's' && v_el
            idx = v_el.text.to_i
            value = @shared_strings[idx] || ''
          elsif v_el
            raw = v_el.text
            value = _parse_number(raw)
          end

          rows[[row, col]] = value
        end
      end

      grid = Array.new(max_row) { Array.new(max_col) }
      rows.each do |(r, c), v|
        grid[r - 1][c - 1] = v
      end
      grid
    end

    def _ref_to_rc(ref)
      col_str = ref.gsub(/[0-9]/, '')
      row_str = ref.gsub(/[A-Za-z]/, '')
      col = 0
      col_str.each_byte { |b| col = col * 26 + (b - 64) }
      [col, row_str.to_i]
    end

    def _parse_number(s)
      return nil if s.nil? || s.empty?
      if s.include?('.') || s.include?('e') || s.include?('E')
        Float(s)
      else
        Integer(s)
      end
    rescue ArgumentError
      s
    end

    # Reads a ZIP file into a hash of { "entry_name" => data_string }.
    # Handles both STORED and DEFLATED entries.
    def _read_zip(path)
      entries = {}
      data = File.binread(path)
      io = StringIO.new(data)

      while io.pos < data.bytesize
        sig = io.read(4)
        break unless sig && sig.unpack1('V') == 0x04034b50

        header = io.read(26)
        version, flags, method, _mtime, _mdate, _crc,
          comp_size, _uncomp_size, name_len, extra_len = header.unpack('vvvvvVVVvv')

        name = io.read(name_len)
        io.read(extra_len) if extra_len > 0

        raw = io.read(comp_size)
        if method == 0
          entries[name] = raw
        elsif method == 8
          entries[name] = Zlib::Inflate.new(-Zlib::MAX_WBITS).inflate(raw)
        end
      end

      entries
    end
  end
end
