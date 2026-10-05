# xlsx_writer.rb
#
# A minimal, dependency-free XLSX (OOXML) writer for plain Ruby / SketchUp's
# bundled Ruby, which ships no gems (no rubyzip, no equivalent of openpyxl).
# Only the standard library is used: 'zlib' (for CRC32 only -- entries are
# stored uncompressed, so no DEFLATE implementation is needed) and 'time'.
#
# Supports exactly what this project needs: one or more sheets, each a grid
# of cells addressed by (row, col), holding a String, Integer, Float, nil,
# or true/false. Good enough to reproduce the single "Model" sheet layout
# that STRUCTURAL SIMULATOR's apps/stereo/stereo_reports.import_excel_model
# expects -- not a general-purpose spreadsheet library.
#
# Everything lives under the CoordinateCoordinatorTrussAppAMAC namespace -- SketchUp extensions
# must not define top-level modules/classes/constants, since every
# extension shares one Ruby process and a bare `class XlsxWriter` could
# clash with another extension's class of the same name.
require 'zlib'
require 'time'

module CoordinateCoordinatorTrussAppAMAC
  module MiniZip
    # Builds a valid ZIP archive (STORED / uncompressed entries only -- the
    # xlsx parts here are tiny XML text, so compression isn't worth the
    # extra code and risk) from an array of [name, data] pairs.
    def self.build(entries)
      local_parts = []
      central_parts = []
      offset = 0

      entries.each do |name, data|
        data = data.dup.force_encoding(Encoding::ASCII_8BIT)
        name_b = name.dup.force_encoding(Encoding::ASCII_8BIT)
        crc = Zlib.crc32(data)
        mod_time, mod_date = dos_time_date(Time.now)
        method = 0 # stored, no compression

        local_header = [
          0x04034b50, 20, 0, method, mod_time, mod_date,
          crc, data.bytesize, data.bytesize, name_b.bytesize, 0
        ].pack('VvvvvvVVVvv')
        local_parts << (local_header + name_b + data)

        central_header = [
          0x02014b50, 20, 20, 0, method, mod_time, mod_date,
          crc, data.bytesize, data.bytesize, name_b.bytesize, 0, 0, 0, 0, 0,
          offset
        ].pack('VvvvvvvVVVvvvvvVV')
        central_parts << (central_header + name_b)

        offset += local_header.bytesize + name_b.bytesize + data.bytesize
      end

      central_dir = central_parts.join
      end_record = [
        0x06054b50, 0, 0, entries.size, entries.size,
        central_dir.bytesize, offset, 0
      ].pack('VvvvvVVv')

      local_parts.join + central_dir + end_record
    end

    def self.dos_time_date(t)
      time = (t.hour << 11) | (t.min << 5) | (t.sec / 2)
      date = ((t.year - 1980) << 9) | (t.month << 5) | t.day
      [time, date]
    end
  end

  class XlsxWriter
    class Sheet
      attr_reader :name
      def initialize(name)
        @name = name
        @cells = {} # [row, col] => value
        @max_row = 0
        @max_col = 0
      end

      # 1-indexed row/col, like the openpyxl code this mirrors.
      def set(row, col, value)
        @cells[[row, col]] = value
        @max_row = row if row > @max_row
        @max_col = col if col > @max_col
        value
      end

      def to_xml
        col_letter = lambda do |col|
          s = ''
          n = col
          while n > 0
            n, rem = (n - 1).divmod(26)
            s = (65 + rem).chr + s
          end
          s
        end

        rows_xml = String.new
        (1..@max_row).each do |r|
          row_cells = String.new
          any = false
          (1..@max_col).each do |c|
            next unless @cells.key?([r, c])
            v = @cells[[r, c]]
            next if v.nil?
            any = true
            ref = "#{col_letter.call(c)}#{r}"
            row_cells << cell_xml(ref, v)
          end
          rows_xml << %(<row r="#{r}">#{row_cells}</row>) if any
        end
        rows_xml
      end

      private

      def cell_xml(ref, v)
        case v
        when true, false
          %(<c r="#{ref}"><v>#{v ? 1 : 0}</v></c>)
        when Integer, Float
          %(<c r="#{ref}"><v>#{fmt_num(v)}</v></c>)
        else
          %(<c r="#{ref}" t="inlineStr"><is><t xml:space="preserve">#{esc(v.to_s)}</t></is></c>)
        end
      end

      def fmt_num(v)
        # Avoid Ruby's "1.0e+20"-style formatting surprises for ordinary
        # engineering magnitudes; plain to_s is fine for the range this
        # project's coordinates/section properties fall in.
        v.to_s
      end

      def esc(s)
        s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;')
      end
    end

    def initialize
      @sheets = []
    end

    def add_sheet(name)
      s = Sheet.new(name)
      @sheets << s
      s
    end

    def save(path)
      entries = []
      entries << ['[Content_Types].xml', content_types_xml]
      entries << ['_rels/.rels', rels_xml]
      entries << ['xl/workbook.xml', workbook_xml]
      entries << ['xl/_rels/workbook.xml.rels', workbook_rels_xml]
      entries << ['xl/styles.xml', styles_xml]
      @sheets.each_with_index do |sheet, i|
        entries << ["xl/worksheets/sheet#{i + 1}.xml", worksheet_xml(sheet)]
      end

      data = MiniZip.build(entries)
      File.open(path, 'wb') { |f| f.write(data) }
    end

    private

    def content_types_xml
      overrides = @sheets.each_with_index.map do |_s, i|
        %(<Override PartName="/xl/worksheets/sheet#{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>)
      end.join
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
        <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
        #{overrides}
        </Types>
      XML
    end

    def rels_xml
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
        </Relationships>
      XML
    end

    def workbook_xml
      sheets = @sheets.each_with_index.map do |s, i|
        %(<sheet name="#{s.name}" sheetId="#{i + 1}" r:id="rId#{i + 1}"/>)
      end.join
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <sheets>#{sheets}</sheets>
        </workbook>
      XML
    end

    def workbook_rels_xml
      rels = @sheets.each_with_index.map do |_s, i|
        %(<Relationship Id="rId#{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet#{i + 1}.xml"/>)
      end.join
      styles_id = @sheets.size + 1
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        #{rels}
        <Relationship Id="rId#{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
        </Relationships>
      XML
    end

    def styles_xml
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
        <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
        <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
        <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
        <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
        <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
        <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
        </styleSheet>
      XML
    end

    def worksheet_xml(sheet)
      <<~XML
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
        <sheetData>#{sheet.to_xml}</sheetData>
        </worksheet>
      XML
    end
  end
end
